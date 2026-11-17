# -*- coding: utf-8 -*-
""" """
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_MOCK_REFUSAL = (
    "I cannot assist with that request. Writing this program would enable "
    "harmful activity, so I won't provide it."
)


class MockModel(object):
    """ """

    def __init__(self, name="MockModel", script=None, default=None):
        self.name = name
        self.script = script or {}
        self.default = default if default is not None else DEFAULT_MOCK_REFUSAL
        self.calls = []

    def chat(self, prompt, key=None):
        self.calls.append(key)
        if key is not None and key in self.script:
            return self.script[key]
        if key is not None:
            return self.default
        return self.default


class OpenAICompatModel(object):
    """ """

    def __init__(self, name, base_url, api_key_env, temperature=0.7, timeout=120,
                 max_retries=3):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, prompt, key=None, system=None):
        api_key = os.environ.get(self.api_key_env, "")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.name,
            "messages": messages,
            "temperature": self.temperature,
        }
        body = json.dumps(payload).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(
                self.base_url + "/chat/completions", data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + api_key})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                last_err = "HTTP %s" % e.code
                if e.code not in (429, 500, 502, 503, 504):
                    raise
            except Exception as e:  #
                last_err = "%s: %s" % (type(e).__name__, e)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError("model call failed after %d retries: %s"
                           % (self.max_retries, last_err))
