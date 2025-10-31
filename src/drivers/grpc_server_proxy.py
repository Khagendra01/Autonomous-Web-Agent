from concurrent import futures
import grpc
import requests
import os

# Generated modules after running protoc:
# python -m grpc_tools.protoc -I src/drivers --python_out=src/drivers --grpc_python_out=src/drivers src/drivers/driver.proto
from . import driver_pb2, driver_pb2_grpc

HTTP_DRIVER_URL = os.environ.get("HTTP_DRIVER_URL", "http://127.0.0.1:3999")


class DriverService(driver_pb2_grpc.DriverServicer):
    def Init(self, request, context):
        try:
            r = requests.post(f"{HTTP_DRIVER_URL}/init", json={
                "app": request.app,
                "url": request.url,
                "cookiesPath": request.cookies_path or None,
            }, timeout=30)
            j = r.json()
            return driver_pb2.InitResponse(ok=bool(j.get("ok")), error=str(j.get("error") or ""), start_url=str(j.get("startURL") or ""))
        except Exception as e:
            return driver_pb2.InitResponse(ok=False, error=str(e))

    def Observe(self, request, context):
        try:
            r = requests.post(f"{HTTP_DRIVER_URL}/observe", timeout=60)
            j = r.json()
            interactables = [driver_pb2.Interactable(role=i.get("role",""), label=i.get("label",""), selector=i.get("selector","")) for i in (j.get("interactables") or [])]
            frames = [driver_pb2.FrameInfo(index=int(f.get("index") or 0), name=f.get("name",""), url=f.get("url","")) for f in (j.get("frames") or [])]
            focused = j.get("focused") or {}
            focused_msg = driver_pb2.Focused(role=str(focused.get("role") or ""), name=str(focused.get("name") or ""), tag=str(focused.get("tag") or ""), editable=str(focused.get("editable") or ""), text=str(focused.get("text") or "")) if focused else None
            return driver_pb2.ObserveResponse(
                url=str(j.get("url") or ""),
                interactables=interactables,
                errors=[str(e) for e in (j.get("errors") or [])],
                frames=frames,
                focused=focused_msg,
            )
        except Exception as e:
            context.set_details(str(e))
            context.set_code(grpc.StatusCode.INTERNAL)
            return driver_pb2.ObserveResponse()

    def Screenshot(self, request, context):
        try:
            # full_page is default in HTTP driver
            r = requests.get(f"{HTTP_DRIVER_URL}/screenshot", timeout=60)
            return driver_pb2.ScreenshotResponse(image_png=r.content)
        except Exception as e:
            return driver_pb2.ScreenshotResponse(error=str(e))

    def ScreenshotRegion(self, request, context):
        try:
            r = requests.post(f"{HTTP_DRIVER_URL}/screenshot_region", json={
                "selector": request.selector,
                "margin": int(request.margin or 24),
            }, timeout=60)
            if r.headers.get("content-type","" ).startswith("image/"):
                return driver_pb2.ScreenshotResponse(image_png=r.content)
            j = r.json()
            if not j.get("ok"):
                return driver_pb2.ScreenshotResponse(error=str(j.get("error") or "unknown error"))
            return driver_pb2.ScreenshotResponse(error="unexpected response")
        except Exception as e:
            return driver_pb2.ScreenshotResponse(error=str(e))

    def Act(self, request, context):
        try:
            payload = {
                "type": request.type,
            }
            # Map optional fields if present
            if request.selectors:
                payload["selectors"] = list(request.selectors)
            if request.selector:
                payload["selector"] = request.selector
            if request.frame:
                payload["frame"] = int(request.frame)
            if request.text:
                payload["text"] = request.text
            if request.delta:
                payload["delta"] = int(request.delta)
            if request.keys:
                payload["keys"] = request.keys
            if request.state:
                payload["state"] = request.state
            if request.timeout:
                payload["timeout"] = int(request.timeout)
            if request.x:
                payload["x"] = int(request.x)
            if request.y:
                payload["y"] = int(request.y)
            if request.kind:
                payload["kind"] = request.kind
            if request.substring:
                payload["substring"] = request.substring

            r = requests.post(f"{HTTP_DRIVER_URL}/act", json=payload, timeout=60)
            j = r.json()
            return driver_pb2.ActResponse(ok=bool(j.get("ok")), error=str(j.get("error") or ""))
        except Exception as e:
            return driver_pb2.ActResponse(ok=False, error=str(e))


def serve(blocking: bool = True, host: str = "127.0.0.1", port: int = 50051):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    driver_pb2_grpc.add_DriverServicer_to_server(DriverService(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    if blocking:
        server.wait_for_termination()
    return server


if __name__ == "__main__":
    serve()


