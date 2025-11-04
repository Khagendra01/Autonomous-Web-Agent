import grpc
from typing import Optional, Sequence
import os, sys

# Ensure generated stubs in this directory are importable as top-level modules
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# Generated modules (ensure protoc run before importing):
import driver_pb2, driver_pb2_grpc


class DriverClient:
    def __init__(self, address: str = "127.0.0.1:50051") -> None:
        self.channel = grpc.insecure_channel(address)
        self.stub = driver_pb2_grpc.DriverStub(self.channel)

    def init(self, app: str, url: str, cookies_path: Optional[str] = None) -> driver_pb2.InitResponse:
        return self.stub.Init(driver_pb2.InitRequest(app=app, url=url, cookies_path=cookies_path or ""))

    def observe(self) -> driver_pb2.ObserveResponse:
        return self.stub.Observe(driver_pb2.ObserveRequest())

    def screenshot(self) -> bytes:
        resp = self.stub.Screenshot(driver_pb2.ScreenshotRequest(full_page=True))
        if resp.error:
            raise RuntimeError(resp.error)
        return bytes(resp.image_png)

    def screenshot_region(self, selector: str, margin: int = 24) -> bytes:
        resp = self.stub.ScreenshotRegion(driver_pb2.ScreenshotRegionRequest(selector=selector, margin=margin))
        if resp.error:
            raise RuntimeError(resp.error)
        return bytes(resp.image_png)

    def act(
        self,
        type: str,
        selectors: Optional[Sequence[str]] = None,
        selector: Optional[str] = None,
        frame: Optional[int] = None,
        text: Optional[str] = None,
        delta: Optional[int] = None,
        keys: Optional[str] = None,
        state: Optional[str] = None,
        timeout: Optional[int] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        kind: Optional[str] = None,
        substring: Optional[str] = None,
        backend_node_id: Optional[int] = None,
    ) -> driver_pb2.ActResponse:
        req = driver_pb2.ActRequest(
            type=type,
            selectors=(list(selectors) if selectors else []),
            selector=(selector or ""),
            frame=(frame or 0),
            text=(text or ""),
            delta=(delta or 0),
            keys=(keys or ""),
            state=(state or ""),
            timeout=(timeout or 0),
            x=(x or 0),
            y=(y or 0),
            kind=(kind or ""),
            substring=(substring or ""),
            backend_node_id=(backend_node_id or 0),
        )
        return self.stub.Act(req)
    
    def smart_locate(
        self,
        description: str,
        failed_selector: Optional[str] = None,
        use_llm: bool = False
    ) -> driver_pb2.SmartLocateResponse:
        """Intelligently find an element using multiple strategies"""
        req = driver_pb2.SmartLocateRequest(
            description=description,
            failed_selector=(failed_selector or ""),
            use_llm=use_llm
        )
        return self.stub.SmartLocate(req)
    
    def close(self) -> driver_pb2.CloseResponse:
        """Close the browser and clean up resources."""
        return self.stub.Close(driver_pb2.CloseRequest())


