"""Lazy, measured OpenAI Responses client. No API key is read at import time."""
import json
import os
from contextvars import ContextVar
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
        self.model = model or os.environ.get('OPENAI_MODEL')
        self.api_calls = 0; self.input_tokens = 0; self.output_tokens = 0
        self.embedding_calls=0;self.embedding_input_tokens=0
        self.usage_known = True; self._client = None

    @property
    def mode(self):
        return 'SCRIPTED_TEST' if self.responder else 'LIVE_OPENAI'

    def ask(self, name, schema, instructions, payload):
        if self.responder:
            value = self.responder(name, payload)
        else:
            if not self.model or not os.environ.get('OPENAI_API_KEY'):
                raise ValueError('Set OPENAI_MODEL and OPENAI_API_KEY in the backend environment.')
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(timeout=_timeout(), max_retries=0)
            self.api_calls += 1  # Counts attempted HTTP SDK calls; retries are disabled.
            try:
                response = self._client.responses.create(model=self.model, store=False,
                    instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
                    max_output_tokens=int(os.getenv('OPENAI_MAX_OUTPUT_TOKENS','12000')),
                    text={'format': {'type':'json_schema','name':name,'strict':True,'schema':schema}})
            except Exception:
                self.usage_known=False
                raise
            usage = getattr(response, 'usage', None)
            if usage and usage.input_tokens is not None and usage.output_tokens is not None:
                self.input_tokens += usage.input_tokens; self.output_tokens += usage.output_tokens
            else:
                self.usage_known = False
            if response.status != 'completed' or not response.output_text:
                raise ValueError('Model response incomplete or refused')
            value = json.loads(response.output_text)
        Draft202012Validator(schema).validate(value)
        return value

    def embeddings(self,texts,model):
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
        input_rate = os.getenv('OPENAI_INPUT_USD_PER_MILLION')
        output_rate = os.getenv('OPENAI_OUTPUT_USD_PER_MILLION')
        cost = 0.0 if self.api_calls==0 else None
        text_calls=self.api_calls-self.embedding_calls
        embedding_rate=os.getenv('OPENAI_EMBEDDING_USD_PER_MILLION')
        if known and (not text_calls or (input_rate and output_rate)) and (not self.embedding_calls or embedding_rate):
            rates=[float(input_rate or 0),float(output_rate or 0),float(embedding_rate or 0)]
            if any(r<0 for r in rates):raise ValueError('Configured prices must be nonnegative')
            cost=((self.input_tokens-self.embedding_input_tokens)*rates[0]+self.output_tokens*rates[1]+self.embedding_input_tokens*rates[2])/1_000_000
        return {'api_calls':self.api_calls,'input_tokens':self.input_tokens if known else None,
                'output_tokens':self.output_tokens if known else None,'estimated_cost_usd':cost}
