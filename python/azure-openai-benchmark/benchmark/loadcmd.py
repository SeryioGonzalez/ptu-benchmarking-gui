# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import json
import logging
import os
import sys
import time
from typing import Iterable, Iterator
from urllib.parse import urlsplit

import aiohttp
import requests
from ping3 import ping

from benchmark.messagegeneration import (
    BaseMessagesGenerator,
    RandomMessagesGenerator
)

from .asynchttpexecuter import AsyncHTTPExecuter
from .oairequester import OAIRequester
from .prometheus_exporter import set_metrics_provider
from .ratelimiting import NoRateLimiter, RateLimiter
from .statsaggregator import _StatsAggregator

logger = logging.getLogger(__name__)

class _RequestBuilder:
    """
    Wrapper iterator class to build request payloads.
    """

    def __init__(
        self,
        messages_generator: BaseMessagesGenerator,
        max_tokens: None,
        completions: None,
        frequence_penalty: None,
        presence_penalty: None,
        temperature: None,
        top_p: None,
        model: None,
    ):
        self.messages_generator = messages_generator
        self.max_tokens = max_tokens
        self.completions = completions
        self.frequency_penalty = frequence_penalty
        self.presence_penalty = presence_penalty
        self.temperature = temperature
        self.top_p = top_p
        self.model = model

    def __iter__(self) -> Iterator[dict]:
        return self

    def __next__(self) -> (dict, int):
        messages, messages_tokens = self.messages_generator.generate_messages()
        body = {"messages": messages}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.completions is not None:
            body["n"] = self.completions
        if self.frequency_penalty is not None:
            body["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty is not None:
            body["presenece_penalty"] = self.presence_penalty
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        # model param is only for openai.com endpoints
        if self.model is not None:
            body["model"] = self.model
        return body, messages_tokens


def load(args):
   try:
      _validate(args)
   except ValueError as e:
      print(f"invalid argument(s): {e}")
      sys.exit(1)

   logger.debug(f"Arguments: {args}")

   run_args = {
      "aggregation_window": args.aggregation_window,
      "api_base_endpoint": args.api_base_endpoint,
      "api_key": args.api_key,
      "api_version": args.api_version,
      "clients": args.clients,
      "completions": args.completions,
      "context_tokens": args.context_tokens,
      "deployment": args.deployment,
      "duration": args.duration,
      "custom_label": args.custom_label,
      "frequency_penalty": args.frequency_penalty,
      "log_request_content": args.log_request_content,
      "max_tokens": args.max_tokens,
      "output_format": args.output_format,
      "presence_penalty": args.presence_penalty,
      "prevent_server_caching": args.prevent_server_caching,
      "rate": args.rate,
      "retry": args.retry,
      "temperature": args.temperature,
      "top_p": args.top_p
   }


   converted = json.dumps(run_args)
   logging.info("Load test args: " + converted)

   api_key = args.api_key
   if not api_key:
      raise ValueError(
         f"API key is not set - make sure to set the API KEY"
      )
   # Check if endpoint is openai.com, otherwise we will assume it is Azure OpenAI
   is_openai_com_endpoint = "openai.com" in args.api_base_endpoint[0]
   # Set URL
   if is_openai_com_endpoint:
      url = args.api_base_endpoint
   else:
      url = (
         args.api_base_endpoint
         + "/openai/deployments/"
         + args.deployment
         + "/chat/completions"
      )
      url += "?api-version=" + args.api_version

   rate_limiter = NoRateLimiter()
   if args.rate is not None and args.rate > 0:
      rate_limiter = RateLimiter(args.rate, 60)

   # Check model name in order to correctly estimate tokens
   logging.info("checking model type...")
   if is_openai_com_endpoint:
      logger.info("openai.com endpoint detected, using model name as-is")
      model = args.deployment
   else:
      # For Azure OpenAI, we need to check the model name
      logger.info("Azure OpenAI endpoint detected, checking model name...")

      model_check_headers = {
         "api-key": api_key,
         "Content-Type": "application/json",
      }
      model_check_body = {"messages": [{"content": "What is 1+1?", "role": "user"}]}
      # Check for model type. If a 429 is returned (due to the endpoint being busy), wait and try again.
      model = None
      while not model:
         response = requests.post(
               url, headers=model_check_headers, json=model_check_body
         )
         logger.debug(f"Model check response: {response.status_code} {response.reason}")
         if response.status_code == 429:
               # Request returned a 429 (endpoint is at full utilization). Sleep and try again to get a valid response
               logger.info("Request returned a 429. Retrying in 0.3 seconds")
               # Sleep for 0.3 seconds
               time.sleep(0.3)
         elif response.status_code not in [200, 429]:
               logger.error(f"Request failed with status code {response.status_code}. Reason: {response.reason}. Data: {response.text}")
               raise ValueError(
                  f"Deployment check failed with status code {response.status_code}. Reason: {response.reason}. Data: {response.text}"
               )
         else:
               logger.debug(f"Request succeeded with status code {response.status_code}. Reason: {response.reason}. Data: {response.text}")
               model = response.json()["model"]
               logger.info(f"Model detected: {model}")

   logging.info(f"model detected: {model}")

   network_latency_adjustment = 0

   max_tokens = args.max_tokens
   context_tokens = args.context_tokens
   
   logging.info(f"using random messages generation with context tokens: {context_tokens}, max tokens: {max_tokens}")
   messages_generator = RandomMessagesGenerator(
      model=model,
      prevent_server_caching=args.prevent_server_caching,
      tokens=context_tokens,
      max_tokens=max_tokens,
   )

   logger.info("Starting load test...")

   request_builder = _RequestBuilder(
      messages_generator=messages_generator,
      max_tokens=max_tokens,
      completions=args.completions,
      frequence_penalty=args.frequency_penalty,
      presence_penalty=args.presence_penalty,
      temperature=args.temperature,
      top_p=args.top_p,
      model=args.deployment if is_openai_com_endpoint else None,
   )

   logging.info("starting load...")

   _run_load(
      request_builder,
      max_concurrency=args.clients,
      api_key=api_key,
      url=url,
      rate_limiter=rate_limiter,
      backoff=args.retry == "exponential",
      duration=args.duration,
      custom_label=args.custom_label,
      aggregation_duration=args.aggregation_window,
      json_output=args.output_format == "jsonl",
      log_request_content=args.log_request_content,
      network_latency_adjustment=network_latency_adjustment,
   )


def _run_load(
    request_builder: Iterable[dict],
    max_concurrency: int,
    api_key: str,
    url: str,
    rate_limiter=None,
    backoff=False,
    duration=None,
    custom_label=None,
    aggregation_duration=60,
    json_output=False,
    log_request_content=False,
    network_latency_adjustment=0,
):
   aggregator = _StatsAggregator(
      window_duration=aggregation_duration,
      dump_duration=1,
      expected_gen_tokens=request_builder.max_tokens,
      clients=max_concurrency,
      custom_label=custom_label,
      json_output=json_output,
      log_request_content=log_request_content,
      network_latency_adjustment=network_latency_adjustment,
   )

    # Start the Prometheus exporter
   set_metrics_provider(aggregator)

   requester = OAIRequester(api_key, url, backoff=backoff)

   async def request_func(session: aiohttp.ClientSession):
      nonlocal aggregator
      nonlocal requester
      request_body, messages_tokens = request_builder.__next__()
      aggregator.record_new_request()
      stats = await requester.call(session, request_body)
      stats.context_tokens = messages_tokens
      try:
         aggregator.aggregate_request(stats)
      except Exception as e:
         print(e)

   def finish_run_func():
      """Function to run when run is finished."""
      nonlocal aggregator
      aggregator.dump_raw_call_stats()

   executer = AsyncHTTPExecuter(
      request_func,
      rate_limiter=rate_limiter,
      max_concurrency=max_concurrency,
      finish_run_func=finish_run_func,
   )
   logger.info("Executing load test")
   aggregator.start()
   executer.run(
      duration=duration
   )
   aggregator.stop()

   logging.info("finished load test")

def _validate(args):
    logger.debug(f"Validating arguments: {args}")

    if not args.api_version:
        raise ValueError("api-version is required")

    if not args.api_key:
        raise ValueError("api-key is required")

    if args.clients is not None and args.clients < 1:
        raise ValueError("clients must be > 0")

    if args.duration is not None and args.duration < 30:
        raise ValueError("duration must be >= 30")

    if args.rate is not None and args.rate < 0:
        raise ValueError("rate must be >= 0")

    if args.max_tokens is not None and args.max_tokens < 0:
        raise ValueError("max-tokens must be >= 0")

    if args.frequency_penalty is not None and not (-2 <= args.frequency_penalty <= 2):
        raise ValueError("frequency-penalty must be between -2.0 and 2.0")

    if args.presence_penalty is not None and not (-2 <= args.presence_penalty <= 2):
        raise ValueError("presence-penalty must be between -2.0 and 2.0")

    if args.temperature is not None and not (0 <= args.temperature <= 2):
        raise ValueError("temperature must be between 0 and 2.0")
    
    logger.info("Arguments validated successfully")

def measure_avg_ping(url: str, num_requests: int = 5, max_time: int = 5):
    """Measures average network latency for a given URL by sending multiple ping requests."""
    ping_url = urlsplit(url).netloc
    latencies = []
    latency_test_start_time = time.time()
    while (
        len(latencies) < num_requests
        and time.time() < latency_test_start_time + max_time
    ):
        delay = ping(ping_url, timeout=5)
        latencies.append(delay)
        if delay < 0.5:  # Ensure at least 0.5 seconds between requests
            time.sleep(0.5 - delay)
    avg_latency = round(
        sum(latencies) / len(latencies), 2
    )  # exclude first request, this is usually 3-5x slower
    return avg_latency
