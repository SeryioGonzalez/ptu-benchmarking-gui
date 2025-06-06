# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import asyncio
import json
import logging
import time
import traceback
from typing import Optional

import aiohttp
import backoff

# TODO: switch to using OpenAI client library once new headers are exposed.

REQUEST_ID_HEADER = "apim-request-id"
RETRY_AFTER_MS_HEADER = "retry-after-ms"
MAX_RETRY_SECONDS = 60.0

TELEMETRY_USER_AGENT_HEADER = "x-ms-useragent"
USER_AGENT = "aoai-benchmark"

class RequestStats:
    """
    Statistics collected for a particular AOAI request.
    """
    def __init__(self):
        self.request_start_time: Optional[float] = None
        self.response_status_code: int = 0
        self.response_time: Optional[float] = None
        self.first_token_time: Optional[float] = None
        self.response_end_time: Optional[float] = None
        self.context_tokens: int = 0
        self.generated_tokens: Optional[int] = None
        self.calls: int = 0
        self.last_exception: Optional[Exception] = None
        self.input_messages: Optional[dict[str, str]] = None
        self.output_content: list[dict] = list()

    def as_dict(self, include_request_content: bool = False) -> dict:
        output = {
            "request_start_time": self.request_start_time,
            "response_status_code": self.response_status_code,
            "response_time": self.response_time,
            "first_token_time": self.first_token_time,
            "response_end_time": self.response_end_time,
            "context_tokens": self.context_tokens,
            "generated_tokens": self.generated_tokens,
            "calls": self.calls,
        }
        if include_request_content:
            output["input_messages"] = self.input_messages
            output["output_content"] = self.output_content if self.output_content else None
        # Add last_exception last, to keep it pretty
        output["last_exception"] = self.last_exception
        return output

def _terminal_http_code(e) -> bool:
    # we only retry on 429
    return e.response.status != 429

class OAIRequester:
    """
    A simple AOAI requester that makes a streaming call and collect corresponding
    statistics.
    :param api_key: Azure OpenAI resource endpoint key.
    :param url: Full deployment URL in the form of https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completins?api-version=<api_version>
    :param backoff: Whether to retry throttled or unsuccessful requests.
    """
    def __init__(self, api_key: str, url: str, backoff=False):
        self.api_key = api_key
        self.url = url
        self.backoff = backoff

    async def call(self, session:aiohttp.ClientSession, body: dict) -> RequestStats:
        """
        Makes a single call with body and returns statistics. The function
        forces the request in streaming mode to be able to collect token
        generation latency.
        In case of failure, if the status code is 429 due to throttling, value
        of header retry-after-ms will be honored. Otherwise, request
        will be retried with an exponential backoff.
        Any other non-200 status code will fail immediately.

        :param body: json request body.
        :return RequestStats.
        """
        stats = RequestStats()
        stats.input_messages = body["messages"]
        # operate only in streaming mode so we can collect token stats.
        body["stream"] = True
        try:
            await self._call(session, body, stats)
        except Exception as e:
            stats.last_exception = traceback.format_exc()
        finally:
        # In case _call itself aborts or throws _before_ setting response_end_time:
            if stats.response_end_time is None:
                stats.response_end_time = time.time()

        return stats

    @backoff.on_exception(backoff.expo,
                      aiohttp.ClientError,
                      jitter=backoff.full_jitter,
                      max_time=MAX_RETRY_SECONDS,
                      giveup=_terminal_http_code)
    async def _call(self, session:aiohttp.ClientSession, body: dict, stats: RequestStats):
        headers = {
            "Content-Type": "application/json",
            TELEMETRY_USER_AGENT_HEADER: USER_AGENT,
        }
        # Add api-key depending on whether it is an OpenAI.com or Azure OpenAI deployment
        if "openai.com" in self.url:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["api-key"] = self.api_key
        stats.request_start_time = time.time()
        while stats.calls == 0 or time.time() - stats.request_start_time < MAX_RETRY_SECONDS:
            stats.calls += 1
            response = await session.post(self.url, headers=headers, json=body)
            stats.response_status_code = response.status
            if response.status != 429:
                break
            if self.backoff and RETRY_AFTER_MS_HEADER in response.headers:
                try:
                    retry_after_str = response.headers[RETRY_AFTER_MS_HEADER]
                    retry_after_ms = float(retry_after_str)
                    logging.debug(f"retry-after sleeping for {retry_after_ms}ms")
                    await asyncio.sleep(retry_after_ms/1000.0)
                except ValueError as e:
                    logging.warning(f"unable to parse retry-after header value: {retry_after_str}: {e}")   
                    # fallback to backoff
                    break
            else:
                # fallback to backoff
                break

        if response.status != 200:
            stats.response_end_time = time.time()
        if response.status != 200 and response.status != 429:
            logging.warning(f"call failed: {REQUEST_ID_HEADER}={response.headers.get(REQUEST_ID_HEADER, None)} {response.status}: {response.reason}")
        if self.backoff:
            response.raise_for_status()
        if response.status == 200:
            await self._handle_response(response, stats)
        
    async def _handle_response(self, response: aiohttp.ClientResponse, stats: RequestStats):
        async with response:
            stats.response_time = time.time()
            try:
                async for line in response.content:
                    # only care about data: frames
                    if not line.startswith(b"data:"):
                        continue

                    text = line.decode("utf-8").strip()
                    # end‐of‐stream sentinel
                    if text == "data: [DONE]":
                        break

                    # remove only the first "data: " prefix
                    payload = text[len("data: "):]
                    try:
                        msg = json.loads(payload)
                    except json.JSONDecodeError:
                        # skip malformed frames
                        continue

                    # skip anything without a choices array
                    choices = msg.get("choices")
                    if not choices or not isinstance(choices, list):
                        continue

                    delta = choices[0].get("delta", {})
                    if not delta:
                        continue

                    # first token timestamp
                    if stats.first_token_time is None:
                        stats.first_token_time = time.time()
                    if stats.generated_tokens is None:
                        stats.generated_tokens = 0

                    # merge into stats.output_content just like before
                    if "role" in delta:
                        stats.output_content.append({"role": delta["role"], "content": ""})
                    else:
                        stats.output_content[-1]["content"] += delta.get("content", "")
                        stats.generated_tokens += 1
            finally:
                stats.response_end_time = time.time()
