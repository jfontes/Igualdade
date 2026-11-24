"""Envio de e-mails transacionais (contratos do Parque das Acácias).

No plano gratuito do PythonAnywhere só o SMTP do Gmail é liberado. Configuração (arquivo WSGI):
    os.environ["SMTP_USUARIO"] = "igualdadeacreana@gmail.com"
    os.environ["SMTP_SENHA"] = "<senha de app do Google, 16 letras>"
Opcionais: SMTP_SERVIDOR (padrão smtp.gmail.com), SMTP_PORTA (465), LOCADOR_EMAIL.

Sem configuração, `enviar` não tenta nada e devolve (False, motivo): as telas mostram o link para
envio manual. Falhas de envio nunca interrompem a vistoria ou a assinatura.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from .config import LOJA, PARQUE

TIMEOUT = 20  # segundos


def configurado() -> bool:
    return bool(os.environ.get("SMTP_USUARIO") and os.environ.get("SMTP_SENHA"))


def email_locador() -> str:
    return os.environ.get("LOCADOR_EMAIL") or PARQUE["email_locador"]


def enviar(para: list[str], assunto: str, texto: str, anexos: list[tuple[str, bytes, str]] = ()) -> tuple[bool, str]:
    """Envia um e-mail. `anexos`: [(nome, bytes, "application/pdf")]. Devolve (ok, mensagem)."""
    destinatarios = [p for p in dict.fromkeys(para) if p]
    if not destinatarios:
        return False, "sem destinatário"
    if not configurado():
        return False, "envio de e-mail não configurado no servidor"
    usuario = os.environ["SMTP_USUARIO"]
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = f"{LOJA['nome']} – {PARQUE['nome']} <{usuario}>"
    msg["To"] = ", ".join(destinatarios)
    msg["Reply-To"] = email_locador()
    msg.set_content(texto)
    for nome, dados, mime in anexos:
        principal, sub = mime.split("/", 1)
        msg.add_attachment(dados, maintype=principal, subtype=sub, filename=nome)
    try:
        with smtplib.SMTP_SSL(os.environ.get("SMTP_SERVIDOR", "smtp.gmail.com"),
                              int(os.environ.get("SMTP_PORTA", "465")),
                              context=ssl.create_default_context(), timeout=TIMEOUT) as smtp:
            smtp.login(usuario, os.environ["SMTP_SENHA"])
            smtp.send_message(msg)
        return True, "enviado"
    except (smtplib.SMTPException, OSError) as e:
        current_app.logger.error("Falha ao enviar e-mail '%s' para %s: %s", assunto, destinatarios, e)
        return False, f"falha no envio ({e.__class__.__name__})"
