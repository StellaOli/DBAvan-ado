import multiprocessing
import subprocess
import time
import json
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from connections import DatabaseConnections
import requests
import uuid
from datetime import datetime
import uvicorn
import logging as logger

from s3_monitor import ServiceMonitor


app = FastAPI()
db = DatabaseConnections()

# Configuração de templates e arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_user(user_id: str) -> dict:
    """Obtém informações completas do usuário para uso nos templates"""
    if not user_id:
        return None
        
    try:
        cursor = db.pg_conn.cursor()
        cursor.execute(
            "SELECT id, name, email, preferences, spotify_id FROM users WHERE id = %s", 
            (user_id,)
        )
        if cursor.rowcount > 0:
            user = cursor.fetchone()
            # Converter preferências de JSON para lista
            preferences = []
            if user[3]:  # Se preferences não é None
                if isinstance(user[3], str):
                    try:
                        preferences = json.loads(user[3])
                    except json.JSONDecodeError:
                        preferences = []
                elif isinstance(user[3], list):
                    preferences = user[3]
            
            return {
                "id": user[0],
                "name": user[1],
                "email": user[2],
                "preferences": preferences,
                "spotify_id": user[4] or ""
            }
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar usuário: {str(e)}")
        return None
    
templates.env.globals["get_user"] = get_user

# Modelos de dados
class UserForm(BaseModel):
    name: str
    email: str
    preferences: str  # Recebido como string separada por vírgulas
    spotify_id: str = ""

class SongForm(BaseModel):
    title: str
    artist: str
    genre: str
    duration: int
    spotify_id: str = ""

class RecommendationForm(BaseModel):
    user_id: str
    current_song: str

def run_s1_api():
    """Inicia o serviço s1_api.py"""
    subprocess.run(["python", "s1_api.py"])

def run_s2_consumer():
    """Inicia o serviço s2_consumer.py"""
    subprocess.run(["python", "s2_consumer.py"])

def run_s3_monitor():
    """Inicia o serviço s3_monitor.py"""
    subprocess.run(["python", "s3_monitor.py"])

@app.on_event("startup")
async def startup_event():
    """Inicia todos os serviços quando o FastAPI iniciar"""
    # Criar processos para cada serviço
    processes = [
        multiprocessing.Process(target=run_s1_api),
        multiprocessing.Process(target=run_s2_consumer),
        multiprocessing.Process(target=run_s3_monitor)
    ]
    
    # Iniciar todos os processos
    for p in processes:
        p.daemon = True  # Permite que os processos terminem quando o main terminar
        p.start()
    
    # Dar tempo para os serviços iniciarem
    time.sleep(3)
    print("Todos os serviços foram iniciados")

# Rotas do frontend
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Rota raiz que redireciona para login ou home conforme autenticação"""
    if request.cookies.get("user_id"):
        return RedirectResponse(url="/home")
    return RedirectResponse(url="/login")

@app.get("/users/create", response_class=HTMLResponse)
async def create_user_form(request: Request):
    return templates.TemplateResponse("create_user.html", {"request": request})

@app.post("/users/create", response_class=HTMLResponse)
async def create_user_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    preferences: str = Form(...),
    spotify_id: str = Form("")
):
    try:
        # Converter preferências para lista
        pref_list = [p.strip() for p in preferences.split(",") if p.strip()]
        
        # Criar usuário via API
        user_data = {
            "name": name,
            "email": email,
            "preferences": pref_list,
            "spotify_id": spotify_id
        }
        
        response = requests.post(
            "http://localhost:8000/users/",
            json=user_data
        )
        response.raise_for_status()
        
        user_id = response.json()["user_id"]
        return RedirectResponse(f"/users/{user_id}", status_code=303)
    
    except Exception as e:
        error_msg = f"Erro ao criar usuário: {str(e)}"
        return templates.TemplateResponse(
            "create_user.html",
            {
                "request": request,
                "error": error_msg,
                "name": name,
                "email": email,
                "preferences": preferences,
                "spotify_id": spotify_id
            },
            status_code=400
        )

@app.get("/users/{user_id}", response_class=HTMLResponse)
async def view_user(request: Request, user_id: str):
    try:
        # Buscar usuário no banco de dados
        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        # Converter preferências de JSON para lista
        preferences = json.loads(user[3]) if user[3] else []
        
        return templates.TemplateResponse(
            "view_user.html",
            {
                "request": request,
                "user": {
                    "id": user[0],
                    "name": user[1],
                    "email": user[2],
                    "preferences": preferences,
                    "spotify_id": user[4]
                }
            }
        )
    except Exception as e:
        error_msg = f"Erro ao buscar usuário: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=400
        )

@app.get("/songs/add", response_class=HTMLResponse)
async def add_song_form(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")
    
    try:
        # Buscar músicas curtidas
        liked_songs = []
        if db.mongo_db is not None and 'likes' in db.mongo_db.list_collection_names():
            liked_songs = list(db.mongo_db.likes.aggregate([
                {"$match": {"user_id": user_id}},
                {"$lookup": {
                    "from": "songs",
                    "localField": "spotify_id",
                    "foreignField": "spotify_id",
                    "as": "song_details"
                }},
                {"$unwind": "$song_details"},
                {"$project": {
                    "title": "$song_details.title",
                    "artist": "$song_details.artist",
                    "genre": "$song_details.genre",
                    "spotify_id": "$song_details.spotify_id"
                }}
            ]))

        recent_songs = []
        if db.mongo_db is not None and 'songs' in db.mongo_db.list_collection_names():
            liked_ids = [s['spotify_id'] for s in liked_songs] if liked_songs else []
            
            recent_songs = list(db.mongo_db.songs.aggregate([
                {"$match": {
                    "spotify_id": {"$exists": True, "$ne": None, "$nin": liked_ids}
                }},
                {"$sort": {"created_at": -1}},
                {"$group": {
                    "_id": "$spotify_id",
                    "doc": {"$first": "$$ROOT"}
                }},
                {"$replaceRoot": {"newRoot": "$doc"}},
                {"$limit": 10}
            ]))

        return templates.TemplateResponse(
            "add_song.html",
            {
                "request": request,
                "liked_songs": liked_songs,
                "recent_songs": recent_songs,
                "user_id": user_id
            }
        )
    except Exception as e:
        logger.error(f"Erro: {str(e)}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})

@app.post("/songs/add", response_class=HTMLResponse)
async def add_song_submit(
    request: Request,
    title: str = Form(...),
    artist: str = Form(...),
    genre: str = Form(...),
    duration: int = Form(...),
    spotify_id: str = Form("")
):
    try:
        user_id = request.cookies.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")
        song_data = {
            "title": title,
            "artist": artist,
            "genre": genre,
            "duration": duration,
            "spotify_id": spotify_id
        }
        
        headers = {"X-User-ID": user_id}
        response = requests.post(
            "http://localhost:8000/songs/",
            json=song_data,
            headers=headers
        )
        response.raise_for_status()
        
        song_id = response.json()["song_id"]
        return RedirectResponse(f"/songs/{response.json()['song_id']}", status_code=303)
    
    except requests.exceptions.HTTPError as http_err:
        error_msg = f"Erro HTTP ao adicionar música: {str(http_err)}"
        try:
            error_details = response.json()
            error_msg += f" - Detalhes: {error_details.get('detail', '')}"
        except:
            pass
    except Exception as e:
        error_msg = f"Erro ao adicionar música: {str(e)}"
    
    return templates.TemplateResponse(
        "add_song.html",
        {
            "request": request,
            "error": error_msg,
            "title": title,
            "artist": artist,
            "genre": genre,
            "duration": duration,
            "spotify_id": spotify_id
        },
        status_code=400
    )

@app.post("/songs/add_from_spotify", response_class=HTMLResponse)
async def add_song_from_spotify(
    request: Request,
    title: str = Form(...),
    artist: str = Form(...),
    genre: str = Form(...),
    duration: int = Form(...),
    spotify_id: str = Form(...),
    user_id: str = Form(...)
):
    try:
        # Verificar se o usuário está autenticado
        if not user_id:
            return RedirectResponse(url="/login", status_code=303)

        song_data = {
            "title": title,
            "artist": artist,
            "genre": genre or "Pop",  # Default genre if empty
            "duration": duration,
            "spotify_id": spotify_id
        }
        
        headers = {"X-User-ID": user_id}
        response = requests.post(
            "http://localhost:8000/songs/",
            json=song_data,
            headers=headers
        )
        response.raise_for_status()
        
        return RedirectResponse(f"/songs/{response.json()['song_id']}", status_code=303)
    
    except requests.exceptions.HTTPError as http_err:
        error_msg = f"Erro ao adicionar música: {http_err}"
        try:
            error_details = response.json()
            error_msg += f" - Detalhes: {error_details.get('detail', '')}"
        except:
            pass
    except Exception as e:
        error_msg = f"Erro ao adicionar música: {str(e)}"
    
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error": error_msg},
        status_code=400
    )

@app.get("/songs/{song_id}", response_class=HTMLResponse)
async def view_song(request: Request, song_id: str):
    try:
        song = db.mongo_db.songs.find_one({"_id": song_id})
        if not song:
            raise HTTPException(status_code=404, detail="Música não encontrada")
        
        return templates.TemplateResponse(
            "view_song.html",
            {
                "request": request,
                "song": song
            }
        )
    except Exception as e:
        error_msg = f"Erro ao buscar música: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=400
        )

@app.get("/recommendations/request", response_class=HTMLResponse)
async def request_recommendation_form(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")
    
    try:
        user = get_user(user_id)
        songs = list(db.mongo_db.songs.find({}, {"title": 1, "artist": 1}).limit(100))
        
        return templates.TemplateResponse(
            "request_recommendation.html",
            {
                "request": request,
                "user": user,
                "songs": songs
            }
        )
    except Exception as e:
        logger.error(f"Erro: {str(e)}")
        return templates.TemplateResponse("error.html", {"request": request, "error": str(e)})

@app.post("/recommendations/request", response_class=HTMLResponse)
async def request_recommendation_submit(
    request: Request,
    user_id: str = Form(...),
    current_song: str = Form(...)
):
    try:
        response = requests.post(
            "http://localhost:8000/recommendations/",
            json={"user_id": user_id, "current_song": current_song}
        )
        response.raise_for_status()
        
        return templates.TemplateResponse(
            "recommendation_submitted.html",
            {
                "request": request,
                "user_id": user_id,
                "current_song": current_song
            }
        )
    
    except Exception as e:
        error_msg = f"Erro ao solicitar recomendação: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=400
        )

@app.get("/spotify/search", response_class=HTMLResponse)
async def spotify_search_form(request: Request):
    return templates.TemplateResponse("spotify_search.html", {"request": request})

@app.post("/spotify/search", response_class=HTMLResponse)
async def spotify_search_submit(
    request: Request,
    query: str = Form(...)
):
    try:
        response = requests.get(
            f"http://localhost:8000/spotify/search?query={query}"
        )
        response.raise_for_status()
        
        results = response.json().get('tracks', {}).get('items', [])
        
        return templates.TemplateResponse(
            "spotify_results.html",
            {
                "request": request,
                "query": query,
                "results": results
            }
        )
    
    except Exception as e:
        error_msg = f"Erro ao buscar no Spotify: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=400
        )

@app.get("/monitor", response_class=HTMLResponse)
async def service_monitor(request: Request):
    try:
        # Verificar status dos serviços
        services = {
            "PostgreSQL": db.pg_conn and db.pg_conn.closed == 0,
            "MongoDB": db.mongo_db is not None,
            "Redis": db.redis_client is not None and db.redis_client.ping(),
            "Kafka": db.kafka_producer is not None,
            "Elasticsearch": db.es_client is not None and db.es_client.ping()
        }
        now = datetime.now()
        return templates.TemplateResponse(
            "monitor.html",
            {
                "request": request,
                "services": services,
                "now": now 
            }
        )
    except Exception as e:
        error_msg = f"Erro ao verificar status dos serviços: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=400
        )
    
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    try:
        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT id, name, email, preferences FROM users")
        users = []
        for row in cursor.fetchall():
            # Correção do JSON - verifica se é string antes de desserializar e 
            # lida com casos onde preferences pode ser None ou lista
            preferences = []
            if row[3]:  # Se preferences não é None
                if isinstance(row[3], str):
                    try:
                        preferences = json.loads(row[3])
                    except json.JSONDecodeError:
                        preferences = []  # ou deixe vazio se preferir
                elif isinstance(row[3], list):  # Se já for uma lista
                    preferences = row[3]

            users.append({
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "preferences": preferences
            })

        return templates.TemplateResponse(
            "login.html",
            {"request": request, "users": users}
        )
    except Exception as e:
        error_msg = f"Erro ao carregar página de login: {str(e)}"
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": error_msg},
            status_code=500  # Retorna 500 para Internal Server Error
        )

@app.get("/login/{user_id}", response_class=HTMLResponse)
async def login_user(request: Request, user_id: str):
    try:
        # Verifica se o usuário existe no banco de dados
        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        # Configura o cookie de autenticação
        response = RedirectResponse(url="/home", status_code=303)
        response.set_cookie(
            key="user_id",
            value=user_id,
            httponly=True,
            max_age=3600,  # 1 hora de expiração
            samesite='Lax',
            secure=False  # True em produção com HTTPS
        )
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no login: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"Falha no login: {str(e)}"},
            status_code=500
        )

@app.get("/home", response_class=HTMLResponse)
async def user_home(request: Request):
    """Página inicial do usuário autenticado"""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    try:
        # Obter informações do usuário
        user = get_user(user_id)
        if not user:
            response = RedirectResponse(url="/login", status_code=303)
            response.delete_cookie("user_id")
            return response

        # Obter estatísticas
        cursor = db.pg_conn.cursor()
        
        # Contagem de usuários
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0] or 0

        # Contagem de músicas (corrigindo a verificação do MongoDB)
        songs_count = 0
        if db.mongo_db is not None:  # Corrigido: verifica se não é None
            try:
                songs_count = db.mongo_db.songs.count_documents({})
            except Exception as e:
                logger.error(f"Erro ao contar músicas: {str(e)}")
                songs_count = 0

        # Contagem de recomendações
        recommendations_count = 0
        if db.mongo_db is not None and hasattr(db.mongo_db, 'recommendations'):
            try:
                recommendations_count = db.mongo_db.recommendations.count_documents({})
            except Exception as e:
                logger.error(f"Erro ao contar recomendações: {str(e)}")
                recommendations_count = 0

        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "users_count": users_count,
                "songs_count": songs_count,
                "recommendations_count": recommendations_count,
                "user": user
            }
        )
        
    except Exception as e:
        logger.error(f"Erro na página home: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"Erro ao carregar a página inicial: {str(e)}"},
            status_code=500
        )
    
@app.get("/monitor/dashboard", response_class=HTMLResponse)
async def monitor_dashboard(request: Request, minutes: int = 5):
    try:
        monitor = ServiceMonitor(db)

        services_status = monitor.check_all_services()
        
        logs_data = monitor.check_elasticsearch_logs(last_minutes=minutes)
        
        if logs_data["status"] != "success":
            raise HTTPException(status_code=500, detail="Erro ao buscar logs")
            
        logs = logs_data["logs"]
        
        # Contar erros e alertas
        error_count = sum(1 for log in logs if log.get("status", "").lower() == "error")
        warning_count = sum(1 for log in logs if log.get("status", "").lower() == "warning")
        
        return templates.TemplateResponse(
            "monitor_dashboard.html",
            {
                "request": request,
                "services_status": services_status,
                "logs": logs,
                "total_logs": logs_data["total"],
                "error_count": error_count,
                "warning_count": warning_count,
                "minutes": minutes,
                "now": datetime.now()
            }
        )
        
    except Exception as e:
        logger.error(f"Erro ao carregar dashboard: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"Erro ao carregar dashboard: {str(e)}"},
            status_code=500
        )

@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_id")
    return response    

@app.on_event("shutdown")
async def shutdown_event():
    """Fecha todas as conexões quando o aplicativo for encerrado"""
    db.close_connections()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
