from django.conf import settings
from django.core.mail import EmailMessage

from Apps.integraciones.models import CorreoEnviado


def enviar_correo(*, usuario, destinatario, asunto, cuerpo, adjunto=None):
    auditoria = CorreoEnviado.objects.create(
        destinatario=destinatario,
        asunto=asunto,
        cuerpo=cuerpo,
        enviado_por=usuario,
    )
    mensaje = EmailMessage(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [destinatario])
    if adjunto:
        mensaje.attach(adjunto.name, adjunto.read(), getattr(adjunto, "content_type", None))
    try:
        mensaje.send(fail_silently=False)
    except Exception as exc:
        auditoria.error = str(exc)
        auditoria.save(update_fields=("error",))
        raise
    auditoria.exitoso = True
    auditoria.save(update_fields=("exitoso",))
    return auditoria
