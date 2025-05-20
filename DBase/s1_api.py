from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from connections import DatabaseConnections
import requests
import json
import uuid
from datetime import datetime
import uvicorn
from typing import Optional
from pymongo.errors import DuplicateKeyError

# Criação da aplicação FastAPI
app = FastAPI()

# Configuração CORS para permitir todas as origens
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todas as origens
    allow_credentials=True,
    allow_methods=["*"],  # Permite todos os métodos
    allow_headers=["*"],  # Permite todos os headers
)

# Inicialização da conexão com o banco de dados
db = DatabaseConnections()

# Modelos Pydantic
class User(BaseModel):
    name: str
    email: str
    preferences: list[str]
    spotify_id: Optional[str] = None

class Song(BaseModel):
    title: str
    artist: str
    genre: str
    duration: int
    spotify_id: Optional[str] = None

class RecommendationRequest(BaseModel):
    user_id: str
    current_song: str

# Autenticação com Spotify
def get_spotify_token():
    auth_url = "https://accounts.spotify.com/api/token"
    auth_response = requests.post(
        auth_url,
        data={"grant_type": "client_credentials"},
        auth=("78df719c6aed403eb01ed1cf9f572d87", "5a3fe8aa5a864a51b1f1207a621520d3")
    )
    return auth_response.json().get("access_token")

# Log para Elasticsearch
def log_to_elasticsearch(message_type, content, status="processed", metadata=None):
    if not db.es_client:
        return
    
    try:
        doc = {
            "message_type": message_type,
            "content": str(content),
            "timestamp": datetime.now(),
            "status": status,
            "metadata": metadata or {}
        }
        db.es_client.index(index="cypher", body=doc)
    except Exception as e:
        print(f"Failed to log to Elasticsearch: {e}")

@app.post("/users/")
async def create_user(user: User):
    try:
        log_to_elasticsearch(
            "api_request",
            f"Starting user creation for {user.email}",
            "started",
            {"endpoint": "/users/", "method": "POST"}
        )

        user_id = str(uuid.uuid4())

        cursor = db.pg_conn.cursor()
        cursor.execute(
            "INSERT INTO users (id, name, email, preferences, spotify_id) VALUES (%s, %s, %s, %s, %s)",
            (user_id, user.name, user.email, json.dumps(user.preferences), user.spotify_id)
        )
        db.pg_conn.commit()

        message = {
            "type": "user_created",
            "data": {
                "user_id": user_id,
                "name": user.name,
                "email": user.email,
                "preferences": user.preferences,
                "spotify_id": user.spotify_id,
                "timestamp": str(datetime.now())
            }
        }

        db.kafka_producer.send("user-actions", message)

        log_to_elasticsearch(
            "api_response",
            f"User created successfully: {user_id}",
            "completed",
            {"user_id": user_id, "email": user.email}
        )

        return {"user_id": user_id}

    except Exception as e:
        log_to_elasticsearch(
            "api_error",
            f"Failed to create user: {str(e)}",
            "error",
            {"error_type": type(e).__name__, "user_email": user.email}
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/songs/")
async def add_song(song: Song, request: Request):
    try:
        user_id = request.headers.get("X-User-ID") or request.cookies.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID não fornecido")

        # Verificar se a música já existe pelo spotify_id
        if song.spotify_id:
            existing_song = db.mongo_db.songs.find_one({"spotify_id": song.spotify_id})
            if existing_song:
                return {"song_id": existing_song["_id"]}  

        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        user_name = user[0]

        song_data = {
            "_id": str(uuid.uuid4()),
            "title": song.title,
            "artist": song.artist,
            "genre": song.genre,
            "duration": song.duration,
            "spotify_id": song.spotify_id,
            "created_at": datetime.now(),
            "added_by": user_id,
            "added_by_name": user_name
        }

        db.mongo_db.songs.insert_one(song_data)

        message = {
            "type": "song_added",
            "data": song_data
        }

        db.kafka_producer.send("user-actions", message)

        log_to_elasticsearch(
            "api_response",
            f"Song added successfully: {song_data['_id']}",
            "completed",
            {"song_id": song_data['_id'], "title": song.title}
        )

        return {"song_id": song_data['_id']}

    except HTTPException as he:
        raise he
    except Exception as e:
        log_to_elasticsearch(
            "api_error",
            f"Failed to add song: {str(e)}",
            "error",
            {"error_type": type(e).__name__, "song_title": song.title}
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/recommendations/")
async def request_recommendation(request: RecommendationRequest):
    try:
        log_to_elasticsearch(
            "api_request",
            f"Recommendation request for user {request.user_id}",
            "started",
            {"endpoint": "/recommendations/", "method": "POST"}
        )

        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE id = %s", (request.user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="User not found")

        message = {
            "type": "recommendation_requested",
            "data": {
                "user_id": request.user_id,
                "current_song": request.current_song,
                "timestamp": str(datetime.now())
            }
        }

        db.kafka_producer.send("recommendation-requests", message)

        log_to_elasticsearch(
            "api_response",
            f"Recommendation request processed for user {request.user_id}",
            "completed",
            {"user_id": request.user_id, "current_song": request.current_song}
        )

        return {"message": "Recommendation request received"}

    except HTTPException as he:
        log_to_elasticsearch(
            "api_error",
            f"User not found for recommendation: {request.user_id}",
            "error",
            {"error_type": "HTTPException", "status_code": he.status_code}
        )
        raise he
    except Exception as e:
        log_to_elasticsearch(
            "api_error",
            f"Failed to process recommendation request: {str(e)}",
            "error",
            {"error_type": type(e).__name__, "user_id": request.user_id}
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/spotify/search")
async def search_spotify(query: str):
    try:
        log_to_elasticsearch(
            "api_request",
            f"Spotify search for: {query}",
            "started",
            {"endpoint": "/spotify/search", "method": "GET"}
        )

        token = get_spotify_token()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            "https://api.spotify.com/v1/search",
            headers=headers,
            params={"q": query, "type": "track", "limit": 5}
        )

        log_to_elasticsearch(
            "api_response",
            f"Spotify search completed for: {query}",
            "completed",
            {"query": query, "result_count": len(response.json().get('tracks', {}).get('items', []))}
        )

        return response.json()

    except Exception as e:
        log_to_elasticsearch(
            "api_error",
            f"Failed to search Spotify: {str(e)}",
            "error",
            {"error_type": type(e).__name__, "query": query}
        )
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/api/liked-songs")
async def get_liked_songs(user_id: str):
    try:
        songs = list(db.mongo_db.likes.find({"user_id": user_id}))
        return songs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/like-song")
async def like_song(request: Request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        song_id = data.get('song_id')
        spotify_id = data.get('spotify_id')
        title = data.get('title')
        artist = data.get('artist')

        if not all([user_id, spotify_id, title, artist]):
            raise HTTPException(status_code=400, detail="Dados incompletos")

        cursor = db.pg_conn.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        if not db.mongo_db.songs.find_one({"spotify_id": spotify_id}):
            raise HTTPException(status_code=404, detail="Música não encontrada")

        try:
            like_data = {
                "user_id": user_id,
                "song_id": song_id,
                "spotify_id": spotify_id,
                "title": title,
                "artist": artist,
                "created_at": datetime.now()
            }
            
            db.mongo_db.likes.insert_one(like_data)
            
        except DuplicateKeyError:
            return {"status": "already_liked"}

        return {"status": "success"}

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)