import io
import qrcode
from qrcode.image.pure import PyPNGImage


def generate_qr_code(url: str) -> bytes:
    """Generate a QR code PNG for the given URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf.read()


def generate_qr_code_base64(url: str) -> str:
    """Generate a QR code as base64-encoded PNG string."""
    import base64
    data = generate_qr_code(url)
    return base64.b64encode(data).decode()
