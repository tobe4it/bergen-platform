"""Local read-only Ollama model discovery inside pre-existing bergen-ai LXC 110.

No Ollama write operations, model pulls or credentials. Plain loopback GET only.
No proxies, no redirects, max 128KB response; no user/document information.
"""
import json
import re
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

FRAME = "BERGEN_AI_CATALOG_PREFLIGHT_OLLAMA_V1:"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run():
    status = {"AUDIT": "READ_ONLY", "CHANGED": False, "API": "UNREACHABLE",
              "MODEL_COUNT": 0, "MODELS": []}
    try:
        req = Request("http://127.0.0.1:11434/api/tags",
                      headers={"Accept": "application/json"}, method="GET")
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=4) as resp:
            blob = resp.read(128001)
            if resp.status != 200 or len(blob) > 128000:
                raise ValueError("API_UNREVIEWED")
        models = json.loads(blob).get("models")
        if not isinstance(models, list) or len(models) > 500:
            raise ValueError("MODEL_LIST_INVALID")
        sanitized = sorted({
            name for entry in models
            if isinstance(entry, dict)
            for name in [entry.get("name")]
            if isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9._:/-]{1,96}", name)
        })
        status.update({"API": "LOCAL_OK", "MODEL_COUNT": len(sanitized),
                       "MODELS": sanitized[:25]})
    except (Exception):
        pass
    print(FRAME + json.dumps(status, sort_keys=True))


run()
