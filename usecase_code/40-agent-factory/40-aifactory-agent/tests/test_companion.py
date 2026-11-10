"""Default-root companion regressions; no Azure, model, microphone or browser sign-in."""
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from aifactory_agent.config import Settings
from aifactory_agent.web import create_app

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "aifactory_agent" / "static"


def test_root_bundles_same_origin_companion_assets_without_changing_security():
    settings = Settings.model_validate(json.loads((ROOT / "config.example.json").read_text("utf-8")))
    with TestClient(create_app(settings), base_url="https://agent.example") as client:
        page = client.get("/")
        assert page.status_code == 200
        assert '<script src="/static/esaif-maui-layout-loader.js" defer></script>' in page.text
        assert "script-src 'self'" in page.headers["content-security-policy"]
        assert "unsafe-eval" not in page.headers["content-security-policy"]
        for name, kind in [
            ("esaif-maui-layout-loader.js", "javascript"),
            ("esaif-maui-layout.js", "javascript"),
            ("esaif-maui-layout.css", "text/css"),
            ("esaif-maui-layout.en.json", "application/json"),
        ]:
            response = client.get("/static/" + name)
            assert response.status_code == 200, name
            assert kind in response.headers["content-type"]
        locale = client.get("/static/esaif-maui-layout.en.json").json()
        assert [locale["gray"], locale["purple"], locale["blueYellow"]] == ["Gray", "Purple", "Blue / Yellow"]
        assert locale["appTitle"] == "Enterprise Scale Azure Factory Agent"
        assert client.get("/api/context").status_code == 503


def test_bare_root_defaults_to_companion_and_legacy_frames_and_foreign_hosts_do_not():
    script = r"""
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const root = process.argv[2];
const loader = fs.readFileSync(root + "/esaif-maui-layout-loader.js", "utf8");
const layout = fs.readFileSync(root + "/esaif-maui-layout.js", "utf8");
function check(url, expected, {frame=false, channel=false}={}) {
  const attributes=new Map(), scripts=[], ready=[], messages=[];
  const window={location:new URL(url),chrome:channel?{webview:{
    addEventListener(){},postMessage:value=>messages.push(value)
  }}:{}};
  window.top=frame?{}:window;
  const document={readyState:"loading",documentElement:{
    hasAttribute:key=>attributes.has(key),setAttribute:(key,value)=>attributes.set(key,value)
  },getElementById:()=>null,createElement:()=>({}),head:{appendChild:node=>scripts.push(node)},
    addEventListener:(event,callback)=>ready.push(callback)};
  const context=vm.createContext({window,document,location:window.location,URL,URLSearchParams,console});
  vm.runInContext(loader,context);
  vm.runInContext(layout,context);
  assert.equal(scripts.length,expected?1:0,url);
  assert.equal(ready.length,expected?1:0,url);
  assert.equal(attributes.get("data-esaif-layout-state"),expected?"loading":undefined,url);
  assert.equal(messages.length,0);
}
for(const url of ["https://agent.example/","https://agent.example/?voice=on",
    "https://agent.example/?layout=companion","http://localhost:8080/",
    "http://127.0.0.1:8080/","http://[::1]:8080/"]) check(url,true);
check("https://agent.example/?host=esaif-maui",true,{channel:true});
for(const url of ["https://agent.example/?layout=legacy","https://agent.example/admin",
    "https://agent.example/?host=other","https://agent.example/?host=esaif-maui",
    "http://agent.example/","http://localhost:8080/?host=esaif-maui"]) check(url,false);
check("https://agent.example/",false,{frame:true});
"""
    result = subprocess.run(["node", "-", str(STATIC)], input=script, text=True,
                            capture_output=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_current_template_satisfies_presentation_node_contract():
    class Nodes(HTMLParser):
        def __init__(self):
            super().__init__()
            self.nodes = {}

        def handle_starttag(self, tag, attrs):
            identifier = dict(attrs).get("id")
            if identifier:
                assert identifier not in self.nodes, "Duplicate DOM identifier: " + identifier
                self.nodes[identifier] = tag.upper()

    parser = Nodes()
    parser.feed((STATIC / "index.html").read_text("utf-8"))
    script = (STATIC / "esaif-maui-layout.js").read_text("utf-8")
    contract = re.search(r"const contract = \{(.*?)\n    \};", script, re.S)
    assert contract, "Companion DOM contract must remain inspectable."
    for identifier, tag in re.findall(r'"([^"]+)": "([^"]+)"', contract.group(1)):
        assert parser.nodes.get(identifier) == tag, identifier
    for identifier in ("voice-toggle", "voice-transcript", "question", "answer", "skill-form", "confirmation-dialog"):
        assert identifier in parser.nodes


def test_companion_keeps_transports_and_credentials_in_the_existing_application():
    script = (STATIC / "esaif-maui-layout.js").read_text("utf-8")
    assert not re.search(r"localStorage|sessionStorage|getUserMedia|WebSocket|XMLHttpRequest|voiceSession\(|accessToken|tokenRequest", script)
    assert 'credentials: "omit"' in script
    css = (STATIC / "esaif-maui-layout.css").read_text("utf-8")
    assert 'data-companion-theme="blue-yellow"' in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".esaif-message-actions" in css
    assert ".esaif-thinking-sweep" in css
