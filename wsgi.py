"""Ponto de entrada WSGI.

No PythonAnywhere, o arquivo de configuração WSGI (aba Web) deve conter:

    import os, sys
    caminho = "/home/SEU_USUARIO/Igualdade"
    if caminho not in sys.path:
        sys.path.insert(0, caminho)
    os.environ["COOKIE_SEGURO"] = "1"
    from wsgi import application

Localmente:  flask --app igualdade run --debug
"""
from igualdade import create_app

application = app = create_app()
