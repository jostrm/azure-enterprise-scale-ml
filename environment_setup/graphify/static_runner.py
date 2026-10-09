"""Run the pinned Graphify CLI with Python network access denied."""
import runpy
import socket
import sys


def deny_network(*args, **kwargs):
    raise OSError("Network access is disabled for local Graphify generation")


def main():
    allowed = (
        sys.argv[1:2] == ["extract"] and "--code-only" in sys.argv and "--no-dedup" in sys.argv
        or sys.argv[1:2] == ["cluster-only"] and "--no-label" in sys.argv
        or sys.argv[1:3] == ["export", "html"]
    )
    if not allowed:
        raise ValueError("Only static extraction, unlabeled clustering and local HTML export are allowed")
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    sys.argv[0] = "graphify"
    runpy.run_module("graphify", run_name="__main__")


if __name__ == "__main__":
    main()
