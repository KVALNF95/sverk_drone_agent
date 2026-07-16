from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from drone_agent_mcp_ros1.mcp_client import McpJsonRpcClient
from drone_agent_mcp_ros1.utils import json_dumps, safe_json_loads


class OpenRouterError(RuntimeError):
    pass


DEFAULT_SYSTEM_PROMPT = """Ты управляешь автономным дроном СВЕРХ/Clover через безопасные высокоуровневые MCP tools.

Отвечай по-русски. Реальные действия с дроном выполняй только через tools. Не утверждай, что действие выполнено, если tool вернул success=false.
Если пользователь задаёт обычный вопрос без управления дроном, отвечай текстом без tool calls.
Если пользователь спрашивает координаты, высоту, заряд, режим или готовность систем — используй drone_get_telemetry или drone_get_system_status.

Основные возможности:
- Телеметрия: drone_get_telemetry, drone_get_system_status.
- Взлёт и посадка: drone_takeoff, drone_land.
- Полёт: drone_navigate, drone_move_relative, drone_set_altitude, drone_set_yaw.
- Безопасная остановка в воздухе: drone_hold_position. Команда «стоп» означает зависнуть, а не выключить моторы.
- Последовательности: drone_run_sequence.
- Светодиодная лента: drone_set_led_effect.
- Общие действия: get_available_tools, wait.

Правила полёта:
- Для «взлети» без высоты используй drone_takeoff height_m=1.0.
- Для «лети вперёд» без расстояния используй drone_move_relative forward_m=0.5.
- forward_m > 0 — вперёд, forward_m < 0 — назад.
- left_m > 0 — влево, left_m < 0 — вправо.
- up_m > 0 — вверх, up_m < 0 — вниз.
- Для абсолютной точки используй drone_navigate. Для карты маркеров frame_id="aruco_map".
- Для последовательных действий используй drone_run_sequence.
- Для «поверни направо» относительный угол отрицательный, для «поверни налево» положительный.
- Для «остановись/зависни» используй drone_hold_position.
- Для «садись/приземлись» используй drone_land.
- Не используй посадку вместо зависания.
- Не пытайся вызывать низкоуровневые set_attitude, set_rates, disarm, shell или прямые MAVROS-команды: таких tools нет.

Безопасность:
- MCP сам ограничивает высоту, скорость, координаты и допустимые фреймы через переменные окружения.
- Если запрос неоднозначен и может привести к опасному полёту, сначала уточни параметры или выбери консервативное значение.
- Перед первым реальным полётом оператор должен проверить сервисы и телеметрию; агент не должен обходить локальные ограничения.

После выполнения кратко скажи, что было сделано, и честно сообщи об ошибках.
По умолчанию заканчивай финальный ответ отдельной фразой: «Бип-буп.»
"""

JSON_PLANNER_PROMPT = """Ты планировщик действий агента SVERH Drone для ROS 1 Clover. Верни только JSON, без markdown и пояснений.

Формат:
{
  "tool_calls": [
    {"name": "tool_name", "arguments": {...}}
  ],
  "reply_after_tools": "короткий русский ответ после выполнения"
}

Доступные tools и схемы:
{tool_schemas}

Правила:
- Обычный вопрос без управления дроном: пустой tool_calls и ответ в reply_after_tools.
- «что ты умеешь» — get_available_tools.
- «где ты / высота / заряд / режим» — drone_get_telemetry.
- «готов ли дрон» — drone_get_system_status.
- «взлети» без высоты — drone_takeoff height_m=1.0.
- «лети вперёд» без расстояния — drone_move_relative forward_m=0.5.
- Вправо задаётся отрицательным left_m; назад — отрицательным forward_m.
- «поверни направо» — drone_set_yaw relative_deg=-90; налево — relative_deg=90.
- «остановись» — drone_hold_position; «садись» — drone_land.
- Для цепочки действий используй один drone_run_sequence.
- Не добавляй неизвестные tools и не вызывай низкоуровневые полётные интерфейсы.
"""


class OpenRouterHost:
    """OpenAI-compatible LLM host.

    The class name is kept for backward compatibility with the first OpenRouter
    version. The preferred runtime configuration now uses OPENAI_* variables:
    OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY. It also supports the older
    OPENROUTER_* and SVERK_* aliases.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = 'https://openrouter.ai/api/v1',
        timeout_s: float = 120.0,
        max_tool_rounds: int = 8,
        http_referer: str | None = None,
        app_title: str = 'sverk-drone-agent',
        system_prompt: str | None = None,
        native_tool_mode: str = 'auto',
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv('OPENAI_API_KEY', '')
            or os.getenv('OPENROUTER_API_KEY', '')
            or os.getenv('SVERK_API_KEY', '')
        )
        self.model = (
            model
            or os.getenv('OPENAI_MODEL', '')
            or os.getenv('OPENROUTER_MODEL', '')
            or os.getenv('SVERK_MODEL', '')
        )
        self.base_url = (
            base_url
            or os.getenv('OPENAI_BASE_URL', '')
            or os.getenv('OPENROUTER_BASE_URL', '')
            or os.getenv('SVERK_BASE_URL', '')
            or 'https://openrouter.ai/api/v1'
        ).rstrip('/')
        self.timeout_s = float(timeout_s)
        self.max_tool_rounds = int(max_tool_rounds)
        self.http_referer = http_referer or os.getenv('OPENROUTER_HTTP_REFERER', '') or 'https://sverk-drone.local'
        self.app_title = app_title
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        mode = str(native_tool_mode or 'auto').strip().lower()
        self.native_tool_mode = mode if mode in {'auto', 'true', 'false'} else 'auto'


    @staticmethod
    def _latin1_header_value(name: str, value: Any, fallback: str = '') -> str:
        """urllib/http.client requires HTTP header values to be latin-1 encodable.

        Robot commands and prompts can contain Cyrillic, but HTTP headers cannot.
        OpenRouter attribution headers are optional, so non-latin-1 characters
        in app_title/referer are safely stripped instead of crashing the agent.
        The Authorization header is never silently modified.
        """
        text = str(value or '')
        try:
            text.encode('latin-1')
            return text
        except UnicodeEncodeError as exc:
            if name.lower() == 'authorization':
                raise OpenRouterError(
                    'LLM API key contains non-latin-1 characters. Check OPENAI_API_KEY / OPENROUTER_API_KEY / SVERK_API_KEY.'
                ) from exc
            cleaned = text.encode('latin-1', errors='ignore').decode('latin-1').strip()
            return cleaned or fallback

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise OpenRouterError('LLM API key is not set. Set OPENAI_API_KEY, OPENROUTER_API_KEY, or SVERK_API_KEY.')
        if not self.model:
            raise OpenRouterError('LLM model is not set. Set OPENAI_MODEL, OPENROUTER_MODEL, or SVERK_MODEL.')

        url = f'{self.base_url}/chat/completions'
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {
            'Authorization': self._latin1_header_value('Authorization', f'Bearer {self.api_key}'),
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'sverk-drone-agent/1.0',
            # OpenRouter uses these; LiteLLM/Sverk normally ignores unknown headers.
            # Keep them latin-1/ASCII-safe: Python's http.client rejects Unicode header values.
            'HTTP-Referer': self._latin1_header_value('HTTP-Referer', self.http_referer, 'https://sverk-drone.local'),
            'X-OpenRouter-Title': self._latin1_header_value('X-OpenRouter-Title', self.app_title, 'sverk-drone-agent'),
            'X-Title': self._latin1_header_value('X-Title', self.app_title, 'sverk-drone-agent'),
        }
        req = Request(url, data=encoded, headers=headers, method='POST')
        try:
            with urlopen(req, timeout=self.timeout_s) as response:
                body = response.read().decode('utf-8')
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='replace')
            raise OpenRouterError(f'LLM HTTP {exc.code}: {body}') from exc
        except URLError as exc:
            raise OpenRouterError(f'LLM connection error: {exc}') from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise OpenRouterError(f'LLM returned non-JSON response: {body[:500]}') from exc

    @staticmethod
    def _mcp_tools_to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in mcp_tools:
            converted.append({
                'type': 'function',
                'function': {
                    'name': tool.get('name', ''),
                    'description': tool.get('description', ''),
                    'parameters': tool.get('inputSchema', {'type': 'object', 'properties': {}}),
                },
            })
        return converted

    @staticmethod
    def _sanitize_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {'role': 'assistant'}
        if 'content' in message:
            cleaned['content'] = message.get('content')
        if message.get('tool_calls'):
            cleaned['tool_calls'] = message.get('tool_calls')
        return cleaned

    @staticmethod
    def _message_content(message: dict[str, Any]) -> str:
        content = message.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    chunks.append(str(part.get('text', '')))
            return '\n'.join(chunks)
        return str(content)

    @staticmethod
    def _extract_json_fallback(content: str) -> list[dict[str, Any]]:
        """Accept {tool_calls:[...]} / {actions:[...]} / single {name,arguments}."""
        text = content.strip()
        if not text:
            return []
        try:
            data = safe_json_loads(text)
        except Exception:
            return []
        calls: list[dict[str, Any]] = []
        if isinstance(data, dict):
            if isinstance(data.get('tool_calls'), list):
                for item in data['tool_calls']:
                    if isinstance(item, dict) and 'name' in item:
                        calls.append({'name': item['name'], 'arguments': item.get('arguments', {})})
            elif isinstance(data.get('actions'), list):
                for item in data['actions']:
                    if isinstance(item, dict):
                        args = dict(item)
                        name = args.pop('type', args.pop('name', ''))
                        if name:
                            calls.append({'name': name, 'arguments': args})
            elif 'name' in data:
                calls.append({'name': data['name'], 'arguments': data.get('arguments', {})})
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    args = dict(item.get('arguments') or item)
                    name = str(item.get('name') or args.pop('type', ''))
                    if name:
                        calls.append({'name': name, 'arguments': args})
        return calls

    def _json_plan_calls(self, text_command: str, mcp_tool_list: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        compact_tools = [
            {
                'name': tool.get('name'),
                'description': tool.get('description'),
                'inputSchema': tool.get('inputSchema'),
            }
            for tool in mcp_tool_list
        ]
        planner_prompt = JSON_PLANNER_PROMPT.replace('{tool_schemas}', json.dumps(compact_tools, ensure_ascii=False))
        planner_prompt += (
            '\n\n# Стиль для поля reply_after_tools\n'
            'Следующий системный промпт описывает только persona и стиль финального текста в reply_after_tools. '
            'Он не отменяет требование вернуть только валидный JSON без markdown.\n'
            + self.system_prompt
        )
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': planner_prompt},
                {'role': 'user', 'content': text_command},
            ],
            'temperature': 0.05,
            'response_format': {'type': 'json_object'},
        }
        try:
            data = self._post_chat(payload)
        except OpenRouterError:
            # Some OpenRouter models/providers do not support response_format.
            # Retry once with the same strict prompt but without that parameter.
            fallback_payload = dict(payload)
            fallback_payload.pop('response_format', None)
            data = self._post_chat(fallback_payload)
        choices = data.get('choices') or []
        if not choices:
            raise OpenRouterError(f'LLM JSON planner response has no choices: {json_dumps(data)}')
        message = choices[0].get('message') or {}
        content = self._message_content(message)
        try:
            parsed = safe_json_loads(content)
        except Exception as exc:
            raise OpenRouterError(f'LLM JSON planner returned non-JSON content: {content[:800]}') from exc
        calls = self._extract_json_fallback(json.dumps(parsed, ensure_ascii=False))
        reply_after_tools = ''
        if isinstance(parsed, dict):
            reply_after_tools = str(parsed.get('reply_after_tools') or '')
        return calls, reply_after_tools

    def _execute_calls(self, calls: list[dict[str, Any]], mcp: McpJsonRpcClient) -> list[dict[str, Any]]:
        tool_results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get('name', ''))
            arguments = dict(call.get('arguments') or {})
            result = mcp.call_tool(name, arguments)
            tool_results.append({'name': name, 'arguments': arguments, 'result': result})
        return tool_results

    @staticmethod
    def _plan_success(tool_results: list[dict[str, Any]], planned_reply: str = '') -> bool:
        if tool_results:
            return all(bool(item.get('result', {}).get('success', False)) for item in tool_results)
        return bool(str(planned_reply or '').strip())

    def _short_report(self, text_command: str, tool_results: list[dict[str, Any]]) -> str:
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': 'Кратко по-русски сообщи, что сделал робот. Не придумывай успех, опирайся только на tool results. Соблюдай стиль агента ниже:\n' + self.system_prompt},
                {'role': 'user', 'content': 'Команда пользователя: ' + text_command + '\nTool results: ' + json.dumps(tool_results, ensure_ascii=False)},
            ],
            'temperature': 0.1,
        }
        try:
            data = self._post_chat(payload)
            choices = data.get('choices') or []
            if choices:
                return self._message_content(choices[0].get('message') or {}).strip() or 'Готово.'
        except Exception:
            pass
        ok = all(bool(item.get('result', {}).get('success', False)) for item in tool_results) if tool_results else False
        return 'Готово.' if ok else 'Команда выполнена с ошибками. Подробности смотри в tool_results.'

    def run_command(self, text_command: str, mcp: McpJsonRpcClient) -> dict[str, Any]:
        mcp.initialize()
        mcp_tool_list = mcp.list_tools()
        tools = self._mcp_tools_to_openai_tools(mcp_tool_list)
        tool_results: list[dict[str, Any]] = []
        transcript: list[dict[str, Any]] = []

        # Some corporate gateways/open models don't support native tool calls.
        # In that case we still use MCP: the LLM returns a JSON plan and the agent
        # executes those tool calls through the local MCP server.
        if self.native_tool_mode == 'false':
            calls, planned_reply = self._json_plan_calls(text_command, mcp_tool_list)
            tool_results = self._execute_calls(calls, mcp)
            return {
                'success': self._plan_success(tool_results, planned_reply),
                'reply': planned_reply or self._short_report(text_command, tool_results),
                'tool_results': tool_results,
                'rounds': 1,
                'model': self.model,
                'llm_base_url': self.base_url,
                'mode': 'json_planner',
            }

        messages: list[dict[str, Any]] = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': text_command},
        ]

        for round_index in range(self.max_tool_rounds):
            payload = {
                'model': self.model,
                'messages': messages,
                'tools': tools,
                'tool_choice': 'auto',
                'temperature': 0.1,
            }
            try:
                data = self._post_chat(payload)
            except OpenRouterError as exc:
                if self.native_tool_mode == 'auto' and round_index == 0:
                    # Fallback for gateways/models that reject the tools/tool_choice params.
                    calls, planned_reply = self._json_plan_calls(text_command, mcp_tool_list)
                    tool_results = self._execute_calls(calls, mcp)
                    return {
                        'success': self._plan_success(tool_results, planned_reply),
                        'reply': planned_reply or self._short_report(text_command, tool_results),
                        'tool_results': tool_results,
                        'rounds': 1,
                        'model': self.model,
                        'llm_base_url': self.base_url,
                        'mode': 'json_planner_after_native_error',
                        'native_error': str(exc),
                    }
                raise

            choices = data.get('choices') or []
            if not choices:
                raise OpenRouterError(f'LLM response has no choices: {json_dumps(data)}')
            message = choices[0].get('message') or {}
            transcript.append({'assistant': message})

            tool_calls = message.get('tool_calls') or []
            if tool_calls:
                messages.append(self._sanitize_assistant_message(message))
                for tool_call in tool_calls:
                    function = tool_call.get('function') or {}
                    name = str(function.get('name', ''))
                    raw_args = function.get('arguments', '{}')
                    try:
                        arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
                    except json.JSONDecodeError:
                        arguments = {}
                    result = mcp.call_tool(name, arguments)
                    tool_results.append({'name': name, 'arguments': arguments, 'result': result})
                    messages.append({
                        'role': 'tool',
                        'tool_call_id': tool_call.get('id', f'call_{round_index}_{name}'),
                        'name': name,
                        'content': json.dumps(result, ensure_ascii=False),
                    })
                continue

            content = self._message_content(message)
            fallback_calls = self._extract_json_fallback(content)
            if fallback_calls:
                tool_results.extend(self._execute_calls(fallback_calls, mcp))
                messages.append({'role': 'assistant', 'content': content})
                messages.append({
                    'role': 'user',
                    'content': 'Tools were executed. Give a short Russian final report based on the tool results: ' + json.dumps(tool_results, ensure_ascii=False),
                })
                continue

            if self.native_tool_mode == 'auto' and round_index == 0 and not tool_results:
                # The model answered normally instead of calling tools. Ask it once as a
                # strict JSON planner. If the planner finds real robot/tool actions, execute them.
                # If it also returns no tool calls, this was an ordinary conversation, so keep the
                # original assistant answer. Otherwise /agent/answer would be replaced by the
                # planner's meta-answer such as "I am a command parser".
                calls, planned_reply = self._json_plan_calls(text_command, mcp_tool_list)
                if calls:
                    tool_results = self._execute_calls(calls, mcp)
                    return {
                        'success': self._plan_success(tool_results, planned_reply),
                        'reply': planned_reply or self._short_report(text_command, tool_results),
                        'tool_results': tool_results,
                        'rounds': round_index + 1,
                        'model': self.model,
                        'llm_base_url': self.base_url,
                        'mode': 'json_planner_after_no_tool_call',
                        'first_answer': content,
                    }
                return {
                    'success': True,
                    'reply': content or planned_reply or 'Готово.',
                    'tool_results': [],
                    'rounds': round_index + 1,
                    'model': self.model,
                    'llm_base_url': self.base_url,
                    'mode': 'ordinary_answer_after_planner_check',
                    'planner_reply': planned_reply,
                }

            return {
                'success': all(bool(item.get('result', {}).get('success', False)) for item in tool_results) if tool_results else True,
                'reply': content or 'Готово.',
                'tool_results': tool_results,
                'rounds': round_index + 1,
                'model': self.model,
                'llm_base_url': self.base_url,
                'mode': 'native_tool_calls',
            }

        return {
            'success': False,
            'reply': 'Превышено максимальное число tool-вызовов.',
            'tool_results': tool_results,
            'model': self.model,
            'llm_base_url': self.base_url,
        }
