import telebot
import json
import time
import smtplib
import re
import threading
from email.message import EmailMessage
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Configuración
TOKEN = "7439134187:AAHBmIgwr6V4phcS1We0kjFJ9r-jyDn7rQA"
EMAIL_DESTINO = "mesadeayuda@gobiernodigital.gob.pe"
EMAIL_ORIGEN = "perezdiazevenronald@gmail.com"
EMAIL_APP_PASSWORD = "jgst vwmi ajyz tsor"
bot = telebot.TeleBot(TOKEN)

# Carga del JSON
with open("chatbot_converted.json", "r", encoding="utf-8") as file:
    chat_data = json.load(file)

user_sessions = {}
inactivity_timers = {}

# Logging
def log_interaction(user_id, message):
    with open("log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(f"{time.ctime()} - {user_id}: {message}\n")

# Inactividad
def reiniciar_sesion(chat_id):
    user_sessions.pop(chat_id, None)
    if chat_id in inactivity_timers:
        inactivity_timers[chat_id].cancel()
        inactivity_timers.pop(chat_id)
    bot.send_message(chat_id, "Hemos reiniciado la conversación por inactividad. Escribe /start para comenzar de nuevo.")

def programar_inactividad(chat_id, minutos=5):
    if chat_id in inactivity_timers:
        inactivity_timers[chat_id].cancel()
    timer = threading.Timer(minutos * 60, lambda: reiniciar_sesion(chat_id))
    inactivity_timers[chat_id] = timer
    timer.start()

# Menú principal
def generar_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for intent in chat_data["intents"]:
        markup.add(KeyboardButton(intent["tag"]))
    return markup

# Submenú dinámico
def generar_submenu(intent):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    for pattern in intent.get("patterns", []):
        markup.add(KeyboardButton(pattern))
    markup.add(KeyboardButton("Volver al menú principal"))
    return markup

# Start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_sessions.pop(chat_id, None)
    log_interaction(chat_id, "/start")
    programar_inactividad(chat_id)
    bot.send_message(chat_id, "¡Hola! Soy tu asistente virtual. ¿Sobre qué tema necesitas información?", reply_markup=generar_menu())

# Saludo
@bot.message_handler(func=lambda m: any(greet in m.text.lower() for greet in ["hola", "buen", "hey", "qué tal"]))
def handle_greetings(message):
    chat_id = message.chat.id
    log_interaction(chat_id, message.text)
    programar_inactividad(chat_id)
    bot.send_message(chat_id, "¡Hola! ¿En qué puedo ayudarte?", reply_markup=generar_menu())

# Manejo general
@bot.message_handler(func=lambda m: True)
def manejar_mensajes(message):
    chat_id = message.chat.id
    texto = message.text.strip()
    log_interaction(chat_id, texto)
    programar_inactividad(chat_id)

    session = user_sessions.get(chat_id, {})

    # Ingreso de datos para correo
    if session.get("estado") == "esperando_email":
        if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', texto):
            session["email"] = texto
            session["estado"] = "esperando_entidad"
            bot.send_message(chat_id, "Ingresa la entidad pública a la que perteneces:")
        else:
            bot.send_message(chat_id, "Correo inválido. Ingresa un correo válido:")
        return

    elif session.get("estado") == "esperando_entidad":
        session["entidad"] = texto
        session["estado"] = "esperando_categoria"
        bot.send_message(chat_id, "Describe brevemente la categoría del problema:")
        return

    elif session.get("estado") == "esperando_categoria":
        session["categoria"] = texto
        session["estado"] = "esperando_consulta"
        bot.send_message(chat_id, "Ingresa los detalles de tu consulta:")
        return

    elif session.get("estado") == "esperando_consulta":
        session["consulta"] = texto
        resumen = (
            f"Correo: {session['email']}\n"
            f"Entidad: {session['entidad']}\n"
            f"Categoría: {session['categoria']}\n"
            f"Consulta: {session['consulta']}"
        )
        bot.send_message(chat_id, f"Confirmación del mensaje:\n\n{resumen}\n\n¿Deseas enviar este correo? (Sí/No)")
        session["estado"] = "confirmar_envio_final"
        return

    elif session.get("estado") == "confirmar_envio_final":
        if texto.lower() == "si":
            enviar_correo(session["email"], session["entidad"], session["categoria"], session["consulta"], chat_id)
        else:
            bot.send_message(chat_id, "Envío cancelado.")
        user_sessions.pop(chat_id, None)
        return

    elif session.get("estado") == "evaluar_utilidad":
        if texto.lower() == "no":
            bot.send_message(chat_id, "¿Deseas enviar un correo con tu consulta detallada? (Sí/No)")
            session["estado"] = "confirmar_envio"
        elif texto.lower() == "si":
            bot.send_message(chat_id, "¡Me alegra haber ayudado! Usa el menú para más información.", reply_markup=generar_menu())
            user_sessions.pop(chat_id, None)
        else:
            bot.send_message(chat_id, "Por favor, responde con Sí o No.")
        return

    elif session.get("estado") == "confirmar_envio":
        if texto.lower() == "si":
            session["estado"] = "esperando_email"
            bot.send_message(chat_id, "Por favor, ingresa tu correo electrónico:")
        else:
            bot.send_message(chat_id, "Entendido. Si necesitas más información, usa el menú.", reply_markup=generar_menu())
            user_sessions.pop(chat_id, None)
        return

    # Submenús y temas
    if texto == "Volver al menú principal":
        bot.send_message(chat_id, "Volviendo al menú principal...", reply_markup=generar_menu())
        user_sessions.pop(chat_id, None)
        return

    # Si el usuario ya seleccionó un tema, busca el intent y responde según el pattern
    if "tema" in session:
        intent = next((i for i in chat_data["intents"] if i["tag"] == session["tema"]), None)
        if intent:
            patterns = intent.get("patterns", [])
            responses = intent.get("responses", [])
            # Busca el pattern seleccionado
            for idx, pattern in enumerate(patterns):
                if texto.lower() == pattern.lower():
                    # Si hay una respuesta para ese pattern, úsala; si no, usa la primera
                    respuesta = responses[idx] if idx < len(responses) else (responses[0] if responses else "No tengo respuesta para esa pregunta.")
                    bot.send_message(chat_id, respuesta)
                    bot.send_message(chat_id, "¿Esta información fue útil? (Sí/No)")
                    session["estado"] = "evaluar_utilidad"
                    user_sessions[chat_id] = session
                    return
            # Si no coincide, sugiere usar el submenú
            bot.send_message(chat_id, "No entendí tu selección. Usa el menú para continuar.", reply_markup=generar_submenu(intent))
            return

    # Selección de tema principal
    for intent in chat_data["intents"]:
        if texto == intent["tag"]:
            user_sessions[chat_id] = {"tema": intent["tag"]}
            bot.send_message(chat_id, "Selecciona una opción:", reply_markup=generar_submenu(intent))
            return

    bot.send_message(chat_id, "No entendí tu mensaje. Usa el menú para continuar.", reply_markup=generar_menu())

# Enviar correo
def enviar_correo(email, entidad, categoria, consulta, chat_id):
    try:
        contenido = f"Correo: {email}\nEntidad: {entidad}\nCategoría: {categoria}\nConsulta: {consulta}"
        msg = EmailMessage()
        msg.set_content(contenido)
        msg["Subject"] = "Consulta desde el bot de Mesa de Ayuda sobre " + categoria
        msg["From"] = EMAIL_ORIGEN
        msg["To"] = EMAIL_DESTINO

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ORIGEN, EMAIL_APP_PASSWORD)
            server.send_message(msg)

        bot.send_message(chat_id, "Tu consulta ha sido enviada. Recibirás una respuesta pronto.")
    except Exception as e:
        bot.send_message(chat_id, f"Error al enviar el correo: {str(e)}")

print("El bot está corriendo...")
bot.polling(none_stop=True)
