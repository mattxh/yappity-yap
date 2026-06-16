"""Shared HTTP session.

Transcription and cleanup hit the same host back-to-back; a keep-alive session
reuses the TCP/TLS connection across those calls (and across dictations), saving a
fresh handshake (~hundreds of ms) each time. All HTTP runs on the single pipeline
worker thread, so one shared Session is safe.
"""
import requests

_SESSION = requests.Session()


def post(url, **kwargs):
    return _SESSION.post(url, **kwargs)
