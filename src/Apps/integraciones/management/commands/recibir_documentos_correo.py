import email
import imaplib
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from Apps.integraciones.services.documentos import guardar_adjunto


class Command(BaseCommand):
    help = "Descarga adjuntos XML/PDF no leídos desde la cuenta de correo configurada."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=50)

    def handle(self, *args, **options):
        host = settings.EMAIL_IMAP_HOST
        usuario = settings.EMAIL_IMAP_USER
        password = settings.EMAIL_IMAP_PASSWORD
        if not all((host, usuario, password)):
            raise CommandError("Configure EMAIL_IMAP_HOST, EMAIL_IMAP_USER y EMAIL_IMAP_PASSWORD.")
        guardados = repetidos = 0
        try:
            with imaplib.IMAP4_SSL(host, settings.EMAIL_IMAP_PORT) as conexion:
                conexion.login(usuario, password)
                conexion.select(settings.EMAIL_IMAP_FOLDER)
                estado, ids = conexion.search(None, "UNSEEN")
                if estado != "OK":
                    raise RuntimeError("Gmail no permitió consultar los mensajes.")
                for message_num in ids[0].split()[-options["limite"]:]:
                    estado, partes = conexion.fetch(message_num, "(RFC822)")
                    if estado != "OK":
                        continue
                    mensaje = email.message_from_bytes(partes[0][1])
                    remitente = parseaddr(mensaje.get("From", ""))[1]
                    asunto = str(make_header(decode_header(mensaje.get("Subject", ""))))
                    recibido = parsedate_to_datetime(mensaje.get("Date")) if mensaje.get("Date") else None
                    message_id = mensaje.get("Message-ID", message_num.decode())
                    for parte in mensaje.walk():
                        nombre = parte.get_filename()
                        if not nombre:
                            continue
                        nombre = str(make_header(decode_header(nombre)))
                        contenido = parte.get_payload(decode=True) or b""
                        _, creado = guardar_adjunto(
                            message_id=message_id,
                            remitente=remitente,
                            asunto=asunto,
                            recibido_en=recibido,
                            nombre=nombre,
                            contenido=contenido,
                        )
                        guardados += int(creado)
                        repetidos += int(not creado)
        except (imaplib.IMAP4.error, OSError, ValueError) as exc:
            raise CommandError(f"No fue posible recibir documentos: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Documentos nuevos: {guardados}; omitidos/repetidos: {repetidos}."))
