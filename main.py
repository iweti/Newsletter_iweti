import os
import re
import hmac
import threading
import smtplib
from email.mime.text import MIMEText
import psycopg2
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# O Nginx fica na frente: sem isso, todo mundo pareceria ter o mesmo IP (127.0.0.1)
app = Flask(__name__)
app.json.ensure_ascii = False
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
CORS(app, origins=['https://iweti.com', 'https://www.iweti.com'])

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri='memory://')

DATABASE_URL = os.environ.get('DATABASE_URL')
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')
EMAIL_FROM = os.environ.get('EMAIL_FROM', GMAIL_USER)
API_KEY = os.environ.get('API_KEY')

EMAIL_REGEX = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


def verificar_api_key():
    chave_enviada = request.headers.get('X-API-Key', '')
    if not API_KEY:
        return False
    return hmac.compare_digest(chave_enviada.encode(), API_KEY.encode())


def obter_email():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return None
    email = dados.get('email')
    if not isinstance(email, str):
        return None
    return email.strip().lower()


def email_valido(email):
    return (
        isinstance(email, str)
        and len(email) <= 254
        and EMAIL_REGEX.match(email) is not None
    )


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inscritos (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()


def enviar_email(destinatario, assunto, corpo):
    msg = MIMEText(corpo)
    msg['Subject'] = assunto
    msg['From'] = EMAIL_FROM
    msg['To'] = destinatario

    with smtplib.SMTP('smtp.gmail.com', 587) as servidor:
        servidor.starttls()
        servidor.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        servidor.send_message(msg)


def enviar_emails_em_lote(emails, assunto, corpo):
    for email in emails:
        try:
            enviar_email(email, assunto, corpo)
        except Exception as e:
            print(f'Erro ao enviar para {email}: {e}')


@app.errorhandler(429)
def limite_excedido(e):
    return jsonify({'erro': 'Muitas tentativas. Tente novamente em instantes.'}), 429


@app.route('/inscrever', methods=['POST'])
@limiter.limit('5 per minute;30 per hour')
def inscrever():
    email = obter_email()
    if not email_valido(email):
        return jsonify({'erro': 'Email inválido'}), 400

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO inscritos (email) VALUES (%s)', (email,))
        conn.commit()
        return jsonify({'sucesso': True})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'erro': 'Email já cadastrado'}), 409
    finally:
        cur.close()
        conn.close()


@app.route('/cancelar-inscricao', methods=['DELETE'])
@limiter.limit('10 per minute')
def cancelar_inscricao():
    if not verificar_api_key():
        return jsonify({'erro': 'Não autorizado'}), 401

    email = obter_email()
    if not email_valido(email):
        return jsonify({'erro': 'Email inválido'}), 400

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM inscritos WHERE email = %s', (email,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'sucesso': True})


@app.route('/enviar-novidade', methods=['POST'])
@limiter.limit('10 per minute')
def enviar_novidade():
    if not verificar_api_key():
        return jsonify({'erro': 'Não autorizado'}), 401

    assunto = request.json.get('assunto')
    corpo = request.json.get('corpo')

    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT email FROM inscritos')
    resultados = cur.fetchall()
    cur.close()
    conn.close()

    emails = [linha[0] for linha in resultados]

    thread = threading.Thread(target=enviar_emails_em_lote, args=(emails, assunto, corpo))
    thread.start()

    return jsonify({'sucesso': True, 'enviando_para': len(emails)})


if __name__ == '__main__':
    init_db()
    app.run(port=5000)