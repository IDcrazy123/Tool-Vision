"""Small JSON client which polls host jobs through Klipper's reactor."""

import json
import urllib.error
import urllib.request


class ClientError(RuntimeError):
    """The ToolVision host service request failed."""


class VisionClient:
    def __init__(self, base_url, reactor):
        self.base_url = base_url.rstrip("/")
        self.reactor = reactor

    def request(self, method, path, payload=None, timeout=5.0):
        data = None
        headers = {"Accept": "application/json", "User-Agent": "ToolVision/3"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except Exception:
                detail = None
            raise ClientError(detail or "host service returned HTTP %d" % exc.code)
        except Exception as exc:
            raise ClientError("cannot contact ToolVision host service: %s" % exc)
        try:
            result = json.loads(body)
        except ValueError:
            raise ClientError("host service returned invalid JSON")
        if isinstance(result, dict) and result.get("ok") is False:
            raise ClientError(result.get("error") or "host service request failed")
        return result

    def configure(self, payload):
        return self.request("POST", "/api/v2/config", payload, timeout=8.0)

    def run_job(self, kind, timeout=20.0):
        job = self.request("POST", "/api/v2/jobs/%s" % kind, {})
        job_id = job.get("id")
        if not job_id:
            raise ClientError("host service returned no job id")
        deadline = self.reactor.monotonic() + float(timeout)
        while self.reactor.monotonic() < deadline:
            current = self.request("GET", "/api/v2/jobs/%s" % job_id)
            status = current.get("status")
            if status == "complete":
                return current.get("result", {})
            if status == "error":
                raise ClientError(current.get("error") or "camera job failed")
            self.reactor.pause(self.reactor.monotonic() + 0.10)
        raise ClientError("camera job timed out after %.1fs" % timeout)
