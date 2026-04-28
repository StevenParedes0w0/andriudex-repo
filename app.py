import os
from flask import Flask, jsonify
from mssql_python import connect
import resend
import threading
from flask import request, jsonify
from twilio.rest import Client

app = Flask(__name__)


def get_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_DATABASE")
    username = os.getenv("DB_USERNAME")
    password = os.getenv("DB_PASSWORD")
    port = os.getenv("DB_PORT", "1433")

    if not server:
        raise ValueError("Falta DB_SERVER")
    if not database:
        raise ValueError("Falta DB_DATABASE")
    if not username:
        raise ValueError("Falta DB_USERNAME")
    if not password:
        raise ValueError("Falta DB_PASSWORD")

    connection_string = (
        f"Server=tcp:{server},{port};"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Authentication=SqlPassword;"
    )

    return connect(connection_string)


@app.route("/")
def home():
    return jsonify({
        "success": True,
        "message": "API Flask funcionando correctamente en Render"
    })


@app.route("/debug-env")
def debug_env():
    if not validar_token(request):
        return jsonify({
            "success": False,
            "message": "Token inválido o no enviado"
        }), 401

    return jsonify({
        "DB_SERVER": os.getenv("DB_SERVER"),
        "DB_DATABASE": os.getenv("DB_DATABASE"),
        "DB_USERNAME": os.getenv("DB_USERNAME"),
        "DB_PASSWORD_EXISTS": bool(os.getenv("DB_PASSWORD")),
        "DB_PORT": os.getenv("DB_PORT"),
    })


@app.route("/test-db")
def test_db():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT GETDATE() AS fecha_servidor")
        row = cursor.fetchone()

        return jsonify({
            "success": True,
            "message": "Conexión a SQL Server exitosa",
            "server_date": str(row[0])
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Error al conectar con SQL Server",
            "error": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/productos")
def listar_productos():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TOP 20 id, nombre, precio, img_url
            FROM productos
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()

        data = []
        for row in rows:
            data.append({
                "id": row[0],
                "nombre": row[1],
                "precio": float(row[2]) if row[2] is not None else None,
                "img_url": row[3],
            })

        return jsonify({
            "success": True,
            "data": data
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": "Error al consultar productos",
            "error": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def validar_token(request):
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return False

    token_esperado = os.environ.get("API_TOKEN")

    if auth_header != f"Bearer {token_esperado}":
        return False

    return True


def enviar_correo_alerta(asunto, mensaje, destino, html=None):
    api_key = os.environ.get("RESEND_API_KEY")
    mail_from = os.environ.get("MAIL_FROM", "onboarding@resend.dev")

    if not api_key:
        raise ValueError("Falta RESEND_API_KEY")

    resend.api_key = api_key
    payload = {
        "from": mail_from,
        "to": [destino],
        "subject": asunto,
        "text": mensaje
    }

    if html:
        payload["html"] = html

    resend.Emails.send(payload)


def enviar_correo_async(asunto, mensaje, destino, html=None):
    try:
        enviar_correo_alerta(asunto, mensaje, destino, html=html)
    except Exception:
        app.logger.exception("Fallo al enviar correo con Resend")


def enviar_whatsapp_alerta(mensaje):
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    whatsapp_from = os.environ.get("TWILIO_WHATSAPP_FROM")
    whatsapp_to = os.environ.get("TWILIO_WHATSAPP_TO")

    if not account_sid or not auth_token or not whatsapp_from or not whatsapp_to:
        return False

    client = Client(account_sid, auth_token)

    client.messages.create(
        from_=whatsapp_from,
        body=mensaje,
        to=whatsapp_to
    )

    return True
    

@app.route("/enviar-alerta", methods=["POST"])
def enviar_alerta():
    try:
        if not validar_token(request):
            return jsonify({
                "success": False,
                "message": "Token inválido o no enviado"
            }), 401

        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "success": False,
                "message": "JSON inválido o vacío"
            }), 400

        destino = data.get("to")
        asunto = data.get("subject")
        mensaje = data.get("message")
        html = data.get("html")

        if not destino or not asunto or not mensaje:
            return jsonify({
                "success": False,
                "message": "Faltan datos"
            }), 400

        threading.Thread(
            target=enviar_correo_async,
            args=(asunto, mensaje, destino, html),
            daemon=True
        ).start()

        return jsonify({
            "success": True,
            "message": "Correo encolado para envio"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)