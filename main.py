import os
import threading
import smtplib
from email.mime.text import MIMEText
import psycopg2
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, origins=['https://iweti.com', 'https://www.iweti.com'])

DATABASE_URL = os.environ.get('DATABASE_URL')
GMAIL_USER = os.environ.get('GMAIL_USER')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD')


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
    msg['From'] = GMAIL_USER
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


@app.route('/inscrever', methods=['POST'])
def inscrever():
    email = request.json.get('email')
    if not email:
        return jsonify({'erro': 'Email obrigatório'}), 400

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
def cancelar_inscricao():
    email = request.json.get('email')
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM inscritos WHERE email = %s', (email,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'sucesso': True})


@app.route('/enviar-novidade', methods=['POST'])
def enviar_novidade():
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
    app.run(debug=False, port=5000)