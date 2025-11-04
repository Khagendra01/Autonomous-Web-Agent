"""CDP helper functions for getting backend_node_id from Playwright."""
from typing import Optional, Dict, Any
try:
    from playwright.sync_api import Page, CDPSession
except ImportError:
    # For type hints only
    Page = Any
    CDPSession = Any


def get_cdp_session(page: Page) -> Optional[CDPSession]:
    """Get CDP session for a Playwright page."""
    try:
        return page.context.new_cdp_session(page)
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Failed to create CDP session: {e}")
        return None


def get_backend_node_id_from_selector(cdp_session: CDPSession, selector: str) -> Optional[int]:
    """
    Get backend_node_id for an element using a selector.
    
    Args:
        cdp_session: Playwright CDP session
        selector: CSS selector or Playwright role selector
        
    Returns:
        backend_node_id if found, None otherwise
    """
    try:
        # First, get the document
        doc_result = cdp_session.send("DOM.getDocument", {"depth": -1})
        if not doc_result or "root" not in doc_result:
            return None
        
        document_node_id = doc_result["root"]["nodeId"]
        
        # Convert Playwright role selector to CSS/XPath if needed
        # For now, we'll use JavaScript to find the element and get its nodeId
        # Then convert nodeId to backendNodeId
        
        # Use JavaScript to find element and get its nodeId
        js_code = f"""
        (() => {{
            try {{
                // Handle Playwright role selectors
                let selector = {repr(selector)};
                let element = null;
                
                if (selector.startsWith('role=')) {{
                    // Parse role selector: role=button[name="text"]
                    const match = selector.match(/role=([^\\[]+)(?:\\[name[*]?="([^"]+)"\\])?/);
                    if (match) {{
                        const role = match[1];
                        const name = match[2] || '';
                        const elements = document.querySelectorAll(`[role="${{role}}"]`);
                        for (const el of elements) {{
                            const text = el.getAttribute('aria-label') || el.innerText || el.textContent || '';
                            if (!name || text.includes(name)) {{
                                element = el;
                                break;
                            }}
                        }}
                    }}
                }} else {{
                    // CSS selector
                    element = document.querySelector(selector);
                }}
                
                if (!element) return null;
                
                // Get a unique identifier we can use to find it via CDP
                // We'll use a combination of attributes
                const id = element.id ? `#${{element.id}}` : '';
                const role = element.getAttribute('role') || '';
                const tag = element.tagName.toLowerCase();
                const text = (element.getAttribute('aria-label') || element.innerText || element.textContent || '').trim().substring(0, 50);
                
                return {{
                    id: id,
                    role: role,
                    tag: tag,
                    text: text,
                    xpath: getXPath(element)
                }};
                
                function getXPath(element) {{
                    if (element.id) return `//*[@id="${{element.id}}"]`;
                    if (element === document.body) return '/html/body';
                    let ix = 0;
                    const siblings = element.parentNode.childNodes;
                    for (let i = 0; i < siblings.length; i++) {{
                        const sibling = siblings[i];
                        if (sibling === element) {{
                            return getXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                        }}
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {{
                            ix++;
                        }}
                    }}
                }}
            }} catch (e) {{
                return {{ error: e.message }};
            }}
        }})()
        """
        
        # Execute JS to get element info
        js_result = cdp_session.send("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": True
        })
        
        if not js_result or "result" not in js_result:
            return None
        
        result_value = js_result["result"].get("value")
        if not result_value or result_value.get("error"):
            return None
        
        # Now use XPath or ID to find the node via CDP
        xpath = result_value.get("xpath")
        elem_id = result_value.get("id")
        
        if elem_id and elem_id.startswith("#"):
            # Try ID selector first (fastest)
            try:
                query_result = cdp_session.send("DOM.querySelector", {
                    "nodeId": document_node_id,
                    "selector": elem_id
                })
                if query_result and "nodeId" in query_result:
                    node_id = query_result["nodeId"]
                    # Get backendNodeId from nodeId
                    describe_result = cdp_session.send("DOM.describeNode", {
                        "nodeId": node_id
                    })
                    if describe_result and "node" in describe_result:
                        return describe_result["node"].get("backendNodeId")
            except Exception:
                pass
        
        # Fallback to XPath
        if xpath:
            try:
                # CDP doesn't have XPath directly, but we can use searchNodes
                # For now, let's use a different approach - find by text and attributes
                search_result = cdp_session.send("DOM.performSearch", {
                    "query": xpath,
                    "includeUserAgentShadowDOM": True
                })
                if search_result and "searchId" in search_result:
                    search_id = search_result["searchId"]
                    try:
                        result = cdp_session.send("DOM.getSearchResults", {
                            "searchId": search_id,
                            "fromIndex": 0,
                            "toIndex": 1
                        })
                        if result and "nodeIds" in result and result["nodeIds"]:
                            node_id = result["nodeIds"][0]
                            describe_result = cdp_session.send("DOM.describeNode", {
                                "nodeId": node_id
                            })
                            if describe_result and "node" in describe_result:
                                backend_node_id = describe_result["node"].get("backendNodeId")
                                # Clean up search
                                try:
                                    cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                                except Exception:
                                    pass
                                return backend_node_id
                    except Exception:
                        # Clean up search on error
                        try:
                            cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                        except Exception:
                            pass
            except Exception:
                pass
        
        return None
        
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Error getting backend_node_id: {e}")
        return None


def get_backend_node_id_from_playwright_locator(
    page: Page,
    cdp_session: CDPSession,
    selector: str
) -> Optional[int]:
    """
    Get backend_node_id using Playwright locator first, then CDP.
    This is more reliable than searching by role+name.
    """
    try:
        # First try to find element using Playwright's evaluate to get the actual DOM element
        # This is more reliable than trying to match by role+name
        try:
            # Check if element exists
            locator = page.locator(selector).first
            count = locator.count()
            if count == 0:
                return None
            
            # Get the element via JavaScript evaluation using the selector
            # This gives us the actual DOM element to query via CDP
            
            # Get element handle via JavaScript evaluation
            js_code = f"""
            (() => {{
                try {{
                    const selector = {repr(selector)};
                    let element = null;
                    
                    // Handle Playwright role selectors
                    if (selector.startsWith('role=')) {{
                        const match = selector.match(/role=([^\\[]+)(?:\\[name[*]?="([^"]+)"\\])?/);
                        if (match) {{
                            const role = match[1];
                            const name = match[2] || '';
                            const elements = document.querySelectorAll(`[role="${{role}}"]`);
                            for (const el of elements) {{
                                const text = (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim();
                                if (!name || text.includes(name) || name.includes(text)) {{
                                    element = el;
                                    break;
                                }}
                            }}
                        }}
                    }} else {{
                        // CSS selector
                        element = document.querySelector(selector);
                    }}
                    
                    if (!element) return null;
                    
                    // Get a unique identifier for CDP lookup
                    return {{
                        id: element.id || '',
                        tag: element.tagName.toLowerCase(),
                        xpath: getXPath(element)
                    }};
                    
                    function getXPath(element) {{
                        if (element.id) return `//*[@id="${{element.id}}"]`;
                        if (element === document.body) return '/html/body';
                        let ix = 0;
                        const siblings = element.parentNode.childNodes;
                        for (let i = 0; i < siblings.length; i++) {{
                            const sibling = siblings[i];
                            if (sibling === element) {{
                                return getXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                            }}
                            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {{
                                ix++;
                            }}
                        }}
                    }}
                }} catch (e) {{
                    return {{ error: e.message }};
                }}
            }})()
            """
            
            js_result = cdp_session.send("Runtime.evaluate", {
                "expression": js_code,
                "returnByValue": True
            })
            
            if not js_result or "result" not in js_result:
                return None
            
            result_value = js_result["result"].get("value")
            if not result_value or result_value.get("error"):
                return None
            
            # Now find the node via CDP using the identifier
            doc_result = cdp_session.send("DOM.getDocument", {"depth": -1})
            if not doc_result or "root" not in doc_result:
                return None
            
            document_node_id = doc_result["root"]["nodeId"]
            
            # Try ID first
            elem_id = result_value.get("id")
            if elem_id:
                try:
                    query_result = cdp_session.send("DOM.querySelector", {
                        "nodeId": document_node_id,
                        "selector": f"#{elem_id}"
                    })
                    if query_result and "nodeId" in query_result:
                        node_id = query_result["nodeId"]
                        describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                        if describe_result and "node" in describe_result:
                            return describe_result["node"].get("backendNodeId")
                except Exception:
                    pass
            
            # Try XPath
            xpath = result_value.get("xpath")
            if xpath:
                try:
                    search_result = cdp_session.send("DOM.performSearch", {
                        "query": xpath,
                        "includeUserAgentShadowDOM": True
                    })
                    if search_result and "searchId" in search_result:
                        search_id = search_result["searchId"]
                        try:
                            result = cdp_session.send("DOM.getSearchResults", {
                                "searchId": search_id,
                                "fromIndex": 0,
                                "toIndex": 1
                            })
                            if result and "nodeIds" in result and result["nodeIds"]:
                                node_id = result["nodeIds"][0]
                                describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                                if describe_result and "node" in describe_result:
                                    backend_node_id = describe_result["node"].get("backendNodeId")
                                    try:
                                        cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                                    except Exception:
                                        pass
                                    return backend_node_id
                        except Exception:
                            try:
                                cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                            except Exception:
                                pass
                except Exception:
                    pass
            
            # BEST METHOD: Use Playwright's locator to get the exact element, then use CDP requestNode
            # This is the most reliable because Playwright finds the actual element, not parent containers
            try:
                locator = page.locator(selector).first
                if locator.count() > 0:
                    # Get element handle from Playwright (this is the ACTUAL element, not parent)
                    handle = locator.evaluate_handle("el => el")
                    
                    # Get objectId from handle
                    object_id = None
                    if hasattr(handle, '_objectId'):
                        object_id = handle._objectId
                    elif hasattr(handle, '_remoteObject'):
                        object_id = handle._remoteObject.get('objectId')
                    
                    if object_id:
                        # Use CDP DOM.requestNode to get nodeId from objectId
                        request_result = cdp_session.send("DOM.requestNode", {"objectId": object_id})
                        if request_result and "nodeId" in request_result:
                            node_id = request_result["nodeId"]
                            describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                            if describe_result and "node" in describe_result:
                                backend_node_id = describe_result["node"].get("backendNodeId")
                                if backend_node_id:
                                    return backend_node_id
            except Exception as e:
                if DEBUG:
                    print(f"[CDP] Playwright locator method failed: {e}")
            
            return None
            
        except Exception as e:
            if DEBUG:
                print(f"[CDP] Error getting backend_node_id from locator: {e}")
            return None
            
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Error in get_backend_node_id_from_playwright_locator: {e}")
        return None


def get_backend_node_id_from_element_info(
    cdp_session: CDPSession,
    role: str,
    name: str,
    tag: str = "",
    elem_id: str = "",
    href: str = "",
    page: Optional[Page] = None,
    selector: Optional[str] = None
) -> Optional[int]:
    """
    Get backend_node_id from element info (role, name, etc.).
    
    If page and selector are provided, uses Playwright locator method (more reliable).
    Otherwise falls back to role+name search.
    """
    # If we have a selector and page, use the more reliable Playwright locator method
    if page and selector:
        return get_backend_node_id_from_playwright_locator(page, cdp_session, selector)
    
    try:
        # Get document
        doc_result = cdp_session.send("DOM.getDocument", {"depth": -1})
        if not doc_result or "root" not in doc_result:
            return None
        
        document_node_id = doc_result["root"]["nodeId"]
        
        # Build search query based on available info
        # Prefer ID, then role+name, then tag+name
        if elem_id:
            try:
                query_result = cdp_session.send("DOM.querySelector", {
                    "nodeId": document_node_id,
                    "selector": f"#{elem_id}"
                })
                if query_result and "nodeId" in query_result:
                    node_id = query_result["nodeId"]
                    describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                    if describe_result and "node" in describe_result:
                        return describe_result["node"].get("backendNodeId")
            except Exception:
                pass
        
        # Try role + name combination
        if role and name:
            # Use JavaScript to find element by role and name
            js_code = f"""
            (() => {{
                try {{
                    const role = {repr(role)};
                    const name = {repr(name)};
                    const elements = document.querySelectorAll(`[role="${{role}}"]`);
                    for (const el of elements) {{
                        const text = (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim();
                        if (text.includes(name) || name.includes(text)) {{
                            return {{
                                tag: el.tagName.toLowerCase(),
                                id: el.id || '',
                                xpath: getXPath(el)
                            }};
                        }}
                    }}
                    return null;
                }} catch (e) {{
                    return {{ error: e.message }};
                }}
                
                function getXPath(element) {{
                    if (element.id) return `//*[@id="${{element.id}}"]`;
                    if (element === document.body) return '/html/body';
                    let ix = 0;
                    const siblings = element.parentNode.childNodes;
                    for (let i = 0; i < siblings.length; i++) {{
                        const sibling = siblings[i];
                        if (sibling === element) {{
                            return getXPath(element.parentNode) + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                        }}
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {{
                            ix++;
                        }}
                    }}
                }}
            }})()
            """
            
            js_result = cdp_session.send("Runtime.evaluate", {
                "expression": js_code,
                "returnByValue": True
            })
            
            if js_result and "result" in js_result:
                result_value = js_result["result"].get("value")
                if result_value and not result_value.get("error"):
                    xpath = result_value.get("xpath")
                    if xpath:
                        try:
                            search_result = cdp_session.send("DOM.performSearch", {
                                "query": xpath,
                                "includeUserAgentShadowDOM": True
                            })
                            if search_result and "searchId" in search_result:
                                search_id = search_result["searchId"]
                                try:
                                    result = cdp_session.send("DOM.getSearchResults", {
                                        "searchId": search_id,
                                        "fromIndex": 0,
                                        "toIndex": 1
                                    })
                                    if result and "nodeIds" in result and result["nodeIds"]:
                                        node_id = result["nodeIds"][0]
                                        describe_result = cdp_session.send("DOM.describeNode", {
                                            "nodeId": node_id
                                        })
                                        if describe_result and "node" in describe_result:
                                            backend_node_id = describe_result["node"].get("backendNodeId")
                                            try:
                                                cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                                            except Exception:
                                                pass
                                            return backend_node_id
                                except Exception:
                                    try:
                                        cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                                    except Exception:
                                        pass
                        except Exception:
                            pass
        
        return None
        
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Error getting backend_node_id from element info: {e}")
        return None


def get_backend_node_id_from_playwright_element(
    page: Page,
    cdp_session: CDPSession,
    selector: str
) -> Optional[int]:
    """
    Get backend_node_id from a Playwright element using its selector.
    This is called at execution time when we have a valid selector.
    Uses Playwright to validate the element exists, then uses CDP to get backend_node_id.
    
    Args:
        page: Playwright page object
        cdp_session: CDP session
        selector: Selector that identifies the element
        
    Returns:
        backend_node_id if found, None otherwise
    """
    try:
        # First validate element exists using Playwright (ensures selector is valid)
        locator = page.locator(selector).first
        count = locator.count()
        if count == 0:
            if DEBUG:
                print(f"[CDP] Element not found for selector: {selector}")
            return None
        
        # Get document for CDP queries
        doc_result = cdp_session.send("DOM.getDocument", {"depth": -1})
        if not doc_result or "root" not in doc_result:
            return None
        
        document_node_id = doc_result["root"]["nodeId"]
        
        # Convert Playwright selector to CDP-compatible selector
        cdp_selector = selector
        
        # Handle role= selectors - convert to CSS
        if selector.startswith('role='):
            # Extract role and name from role=button[name="text"]
            import re
            match = re.match(r'role=([^\[]+)(?:\[name[*]?="([^"]+)"\])?', selector)
            if match:
                role = match.group(1)
                name = match.group(2) if match.group(2) else None
                if name:
                    # Try to find by role and accessible name
                    cdp_selector = f'[role="{role}"][aria-label*="{name}"]'
                else:
                    cdp_selector = f'[role="{role}"]'
        
        # Try CDP querySelector first (fastest for simple selectors)
        try:
            query_result = cdp_session.send("DOM.querySelector", {
                "nodeId": document_node_id,
                "selector": cdp_selector
            })
            if query_result and "nodeId" in query_result and query_result["nodeId"] > 0:
                node_id = query_result["nodeId"]
                describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                if describe_result and "node" in describe_result:
                    backend_node_id = describe_result["node"].get("backendNodeId")
                    if backend_node_id:
                        if DEBUG:
                            print(f"[CDP] Found backend_node_id {backend_node_id} via querySelector")
                        return backend_node_id
        except Exception as e:
            if DEBUG:
                print(f"[CDP] querySelector failed for {cdp_selector}: {e}")
        
        # PRIMARY METHOD: Use Playwright's evaluateHandle to get element, then use CDP requestNode
        # This is the MOST reliable because Playwright finds the actual element, not parent containers
        try:
            # Get element handle from Playwright (this is the ACTUAL element Playwright found)
            handle = locator.evaluate_handle("el => el")
            
            # Get objectId from the handle (Playwright JSHandle has _objectId)
            object_id = None
            if hasattr(handle, '_objectId'):
                object_id = handle._objectId
            elif hasattr(handle, '_remoteObject'):
                object_id = handle._remoteObject.get('objectId')
            
            if object_id:
                # Use CDP DOM.requestNode to get nodeId from objectId (most direct and reliable)
                try:
                    request_result = cdp_session.send("DOM.requestNode", {"objectId": object_id})
                    if request_result and "nodeId" in request_result:
                        node_id = request_result["nodeId"]
                        describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                        if describe_result and "node" in describe_result:
                            backend_node_id = describe_result["node"].get("backendNodeId")
                            if backend_node_id:
                                print(f"  [CDP] ✓ Resolved backend_node_id {backend_node_id} via Playwright locator + requestNode")
                                return backend_node_id
                except Exception as e:
                    print(f"  [CDP] ⚠️  requestNode failed: {e}")
            
        except Exception as e:
            print(f"  [CDP] ⚠️  Playwright evaluateHandle failed: {e}")
        
        # Last resort: Use JavaScript evaluation to get element info, then XPath
        try:
            # Get element's ID or generate XPath via JS
            element_info = locator.evaluate("""
                el => {
                    if (!el) return null;
                    return {
                        id: el.id || '',
                        tag: el.tagName.toLowerCase(),
                        xpath: (() => {
                            if (el.id) return `//*[@id="${el.id}"]`;
                            let path = '';
                            for (; el && el.nodeType === 1; el = el.parentNode) {
                                let idx = 1;
                                for (let sib = el.previousSibling; sib; sib = sib.previousSibling) {
                                    if (sib.nodeType === 1 && sib.tagName === el.tagName) idx++;
                                }
                                path = '/' + el.tagName.toLowerCase() + '[' + idx + ']' + path;
                            }
                            return path;
                        })()
                    };
                }
            """)
            
            if element_info and element_info.get("id"):
                # Try ID selector
                try:
                    query_result = cdp_session.send("DOM.querySelector", {
                        "nodeId": document_node_id,
                        "selector": f"#{element_info['id']}"
                    })
                    if query_result and "nodeId" in query_result and query_result["nodeId"] > 0:
                        node_id = query_result["nodeId"]
                        describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                        if describe_result and "node" in describe_result:
                            backend_node_id = describe_result["node"].get("backendNodeId")
                            if backend_node_id:
                                if DEBUG:
                                    print(f"[CDP] Found backend_node_id {backend_node_id} via element ID")
                                return backend_node_id
                except Exception:
                    pass
            
            # Try XPath search
            xpath = element_info.get("xpath") if element_info else None
            if xpath:
                try:
                    search_result = cdp_session.send("DOM.performSearch", {
                        "query": xpath,
                        "includeUserAgentShadowDOM": True
                    })
                    if search_result and "searchId" in search_result:
                        search_id = search_result["searchId"]
                        try:
                            result = cdp_session.send("DOM.getSearchResults", {
                                "searchId": search_id,
                                "fromIndex": 0,
                                "toIndex": 1
                            })
                            if result and "nodeIds" in result and result["nodeIds"]:
                                node_id = result["nodeIds"][0]
                                describe_result = cdp_session.send("DOM.describeNode", {"nodeId": node_id})
                                if describe_result and "node" in describe_result:
                                    backend_node_id = describe_result["node"].get("backendNodeId")
                                    try:
                                        cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                                    except Exception:
                                        pass
                                    if backend_node_id:
                                        if DEBUG:
                                            print(f"[CDP] Found backend_node_id {backend_node_id} via XPath")
                                        return backend_node_id
                        except Exception as e:
                            if DEBUG:
                                print(f"[CDP] XPath lookup failed: {e}")
                        finally:
                            try:
                                cdp_session.send("DOM.discardSearchResults", {"searchId": search_id})
                            except Exception:
                                pass
                except Exception as e:
                    if DEBUG:
                        print(f"[CDP] XPath search failed: {e}")
        except Exception as e:
            if DEBUG:
                print(f"[CDP] JS evaluation fallback failed: {e}")
        
        return None
        
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Error in get_backend_node_id_from_playwright_element: {e}")
        return None


def click_by_backend_node_id(cdp_session: CDPSession, backend_node_id: int) -> bool:
    """
    Click an element using its backend_node_id.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Convert backend_node_id to node_id
        push_result = cdp_session.send("DOM.pushNodesByBackendIdsToFrontend", {
            "backendNodeIds": [backend_node_id]
        })
        
        if not push_result or "nodeIds" not in push_result or not push_result["nodeIds"]:
            return False
        
        node_id = push_result["nodeIds"][0]
        
        # Resolve node to get object ID
        resolve_result = cdp_session.send("DOM.resolveNode", {
            "nodeId": node_id
        })
        
        if not resolve_result or "object" not in resolve_result or "objectId" not in resolve_result["object"]:
            return False
        
        object_id = resolve_result["object"]["objectId"]
        
        # Scroll into view
        try:
            cdp_session.send("DOM.scrollIntoViewIfNeeded", {
                "backendNodeId": backend_node_id
            })
        except Exception:
            pass
        
        # Get bounding box for click coordinates
        box_model = cdp_session.send("DOM.getBoxModel", {
            "nodeId": node_id
        })
        
        if box_model and "model" in box_model and "content" in box_model["model"]:
            content = box_model["model"]["content"]
            if len(content) >= 8:
                # Calculate center point
                x = (content[0] + content[2] + content[4] + content[6]) / 4
                y = (content[1] + content[3] + content[5] + content[7]) / 4
                
                # Click at coordinates
                cdp_session.send("Input.dispatchMouseEvent", {
                    "type": "mousePressed",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1
                })
                cdp_session.send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1
                })
                
                return True
        
        # Fallback: use JavaScript click
        js_result = cdp_session.send("Runtime.callFunctionOn", {
            "objectId": object_id,
            "functionDeclaration": "function() { this.click(); return true; }",
            "returnByValue": True
        })
        
        if js_result and "result" in js_result:
            result_value = js_result["result"].get("value")
            return result_value is True
        
        return False
        
    except Exception as e:
        if DEBUG:
            print(f"[CDP] Error clicking by backend_node_id: {e}")
        return False


# DEBUG flag - can be set by parent module
DEBUG = False

