"""Lazy, measured OpenAI Responses client. No API key is read at import time."""
import json
import os
from contextvars import ContextVar
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from jsonschema import Draft202012Validator

_current = ContextVar('harbourline_gateway', default=None)


def _timeout():
    """Seconds to wait for one model call; long structured outputs can exceed a minute."""
    try:
        return max(30.0, float(os.getenv('OPENAI_TIMEOUT_SECONDS', '180')))
    except ValueError:
        return 180.0


class ModelGateway:
    def __init__(self, *, responder=None, model=None):
        self.responder = responder
        self.provider = os.getenv('MODEL_PROVIDER', 'openai').lower()
        if self.provider not in ('openai', 'gemini', 'openrouter'):
            raise ValueError('MODEL_PROVIDER must be openai, gemini or openrouter')
        self.model = model or os.environ.get(self.provider.upper() + '_MODEL')
        self.api_calls = 0; self.input_tokens = 0; self.output_tokens = 0
        self.embedding_calls=0;self.embedding_input_tokens=0
        self.usage_known = True; self._client = None

    @property
    def mode(self):
        return 'SCRIPTED_TEST' if self.responder else 'LIVE_' + self.provider.upper()

    def ask(self, name, schema, instructions, payload):
        if self.responder:
            value = self.responder(name, payload)
        elif self.provider == 'gemini':
            value = self.ask_gemini(schema, instructions, payload)
        elif self.provider == 'openrouter':
            value = self.ask_openrouter(name, schema, instructions, payload)
        else:
            if not self.model or not os.environ.get('OPENAI_API_KEY'):
                raise ValueError('Set OPENAI_MODEL and OPENAI_API_KEY in the backend environment.')
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(timeout=_timeout(), max_retries=0)
            from openai import RateLimitError
            # Reasoning models (e.g. gpt-6-luna) accept an effort level; others reject the field,
            # so it is sent only when OPENAI_REASONING_EFFORT is set (none/low/medium/high/xhigh).
            extra = {}
            if os.getenv('OPENAI_REASONING_EFFORT'):
                extra['reasoning'] = {'effort': os.getenv('OPENAI_REASONING_EFFORT')}

            for attempt in range(3):
                self.api_calls += 1
                try:
                    response = self._client.responses.create(
                        model=self.model, store=False, instructions=instructions,
                        input=json.dumps(payload, ensure_ascii=False),
                        max_output_tokens=int(os.getenv('OPENAI_MAX_OUTPUT_TOKENS','32000')),
                        text={'format': {'type':'json_schema','name':name,'strict':True,'schema':schema}},
                        **extra,
                    )
                except RateLimitError as exc:
                    # Only retry a temporary throttle. A quota/billing error needs an operator.
                    if attempt == 2 or exc.code != 'rate_limit_exceeded':
                        self.usage_known = False
                        raise
                    try:
                        delay = float(exc.response.headers.get('Retry-After', '60'))
                    except ValueError:
                        delay = 60
                    if not 0 <= delay <= 120:
                        self.usage_known = False
                        raise
                    sleep(max(2, delay))
                except Exception:
                    self.usage_known = False
                    raise
                else:
                    break
            usage = getattr(response, 'usage', None)
            if usage and usage.input_tokens is not None and usage.output_tokens is not None:
                self.input_tokens += usage.input_tokens; self.output_tokens += usage.output_tokens
            else:
                self.usage_known = False
            if response.status != 'completed' or not response.output_text:
                reason = getattr(getattr(response, 'incomplete_details', None), 'reason', None)
                hint = (' (raise OPENAI_MAX_OUTPUT_TOKENS: reasoning models count their thinking '
                        'against this limit)' if reason == 'max_output_tokens' else '')
                raise ValueError(f'Model response incomplete or refused in {name}: '
                                 f'{reason or response.status}{hint}')
            value = json.loads(response.output_text)
        Draft202012Validator(schema).validate(value)
        return value

    def ask_openrouter(self, name, schema, instructions, payload):
        key = os.getenv('OPENROUTER_API_KEY')
        free_model = bool(self.model and (self.model.endswith(':free') or self.model == 'openrouter/free'))
        if not key or not (free_model or self.model == 'openai/gpt-4.1-mini'):
            raise ValueError('OpenRouter requires a key and a supported free model or openai/gpt-4.1-mini.')
        data = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': instructions},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
            ],
            'response_format': {
                'type': 'json_schema',
                'json_schema': {'name': name, 'strict': True, 'schema': schema},
            },
            'provider': {'require_parameters': True, 'data_collection': 'deny'},
        }
        while True:
            request = Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(data).encode(),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key},
            )
            self.api_calls += 1
            try:
                with urlopen(request, timeout=120) as response:
                    result = json.load(response)
                self.model = data['model']
                break
            except HTTPError as exc:
                if exc.code == 404 and free_model and data['model'] != 'openrouter/free':
                    data['model'] = 'openrouter/free'
                    continue
                self.usage_known = False
                raise RuntimeError(f'OpenRouter request failed (HTTP {exc.code})') from None
            except (URLError, TimeoutError):
                self.usage_known = False
                raise RuntimeError('OpenRouter request timed out or could not connect') from None
        usage = result.get('usage') or {}
        if usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None:
            self.input_tokens += usage['prompt_tokens']
            self.output_tokens += usage['completion_tokens']
        else:
            self.usage_known = False
        choices = result.get('choices') or []
        if not choices or choices[0].get('finish_reason') != 'stop':
            raise ValueError('OpenRouter response incomplete or refused')
        return json.loads(choices[0]['message']['content'])

    def ask_gemini(self, schema, instructions, payload):
        key = os.getenv('GEMINI_API_KEY')
        if not self.model or not key:
            raise ValueError('Set GEMINI_MODEL and GEMINI_API_KEY in the backend environment.')
        model = quote(self.model.removeprefix('models/'), safe='')
        data = {
            'systemInstruction': {'parts': [{'text': instructions}]},
            'contents': [{'parts': [{'text': json.dumps({
                'task_input': payload, 'required_output_schema': schema,
                'output_instruction': 'Return exactly one JSON object that validates against this schema.',
            }, ensure_ascii=False)}]}],
            'generationConfig': {
                'responseMimeType': 'application/json',
                'maxOutputTokens': int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS', '24000')),
            },
        }
        request = Request(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'x-goog-api-key': key},
        )
        self.api_calls += 1
        try:
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
        except HTTPError as exc:
            self.usage_known = False
            raise RuntimeError(f'Gemini request failed (HTTP {exc.code})') from None
        except (URLError, TimeoutError):
            self.usage_known = False
            raise RuntimeError('Gemini request timed out or could not connect') from None
        usage = result.get('usageMetadata', {})
        if 'promptTokenCount' in usage and 'candidatesTokenCount' in usage:
            self.input_tokens += usage['promptTokenCount']
            self.output_tokens += usage['candidatesTokenCount'] + usage.get('thoughtsTokenCount', 0)
        else:
            self.usage_known = False
        candidates = result.get('candidates', [])
        if not candidates or candidates[0].get('finishReason') != 'STOP':
            raise ValueError('Gemini response incomplete or refused')
        parts = candidates[0].get('content', {}).get('parts', [])
        return json.loads(''.join(part.get('text', '') for part in parts if not part.get('thought')))

    def embeddings(self,texts,model):
        if self.provider != 'openai':
            raise ValueError('Use lexical retrieval with this reporting route')
        if self.responder:
            raise ValueError('Embeddings are not available in scripted tests')
        if not os.environ.get('OPENAI_API_KEY'):raise ValueError('OPENAI_API_KEY is required')
        if self._client is None:
            from openai import OpenAI
            self._client=OpenAI(timeout=_timeout(),max_retries=0)
        self.api_calls+=1;self.embedding_calls+=1
        try:response=self._client.embeddings.create(model=model,input=texts)
        except Exception:
            self.usage_known=False
            raise
        usage=getattr(response,'usage',None)
        if usage and usage.prompt_tokens is not None:
            self.input_tokens+=usage.prompt_tokens;self.embedding_input_tokens+=usage.prompt_tokens
        else:self.usage_known=False
        rows=sorted(response.data,key=lambda r:r.index)
        if len(rows)!=len(texts):raise ValueError('Embedding response size mismatch')
        return [r.embedding for r in rows]

    def metrics(self):
        # Prices are configurable, never invented. Scripted tests have no API/token usage.
        if self.responder:
            return {'api_calls':0,'input_tokens':0,'output_tokens':0,'estimated_cost_usd':0.0}
        known = self.usage_known
        input_rate = os.getenv(self.provider.upper() + '_INPUT_USD_PER_MILLION')
        output_rate = os.getenv(self.provider.upper() + '_OUTPUT_USD_PER_MILLION')
        cost = 0.0 if self.api_calls==0 else None
        text_calls=self.api_calls-self.embedding_calls
        embedding_rate=os.getenv('OPENAI_EMBEDDING_USD_PER_MILLION')
        if known and (not text_calls or (input_rate and output_rate)) and (not self.embedding_calls or embedding_rate):
            rates=[float(input_rate or 0),float(output_rate or 0),float(embedding_rate or 0)]
            if any(r<0 for r in rates):raise ValueError('Configured prices must be nonnegative')
            cost=((self.input_tokens-self.embedding_input_tokens)*rates[0]+self.output_tokens*rates[1]+self.embedding_input_tokens*rates[2])/1_000_000
        return {'api_calls':self.api_calls,'input_tokens':self.input_tokens if known else None,
                'output_tokens':self.output_tokens if known else None,'estimated_cost_usd':cost}
