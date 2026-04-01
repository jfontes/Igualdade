from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
import os

app = FastAPI()

# Permite que o PWA (Vercel) acesse a API (Render)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelo simplificado para receber o cadastro completo
class FamiliarSchema(BaseModel):
    nome: str
    tipo_parentesco: str
    data_nascimento: Optional[date]

class ObreiroSchema(BaseModel):
    nome: str
    cim: str
    cpf: str
    data_nascimento: date
    # ... (adicione as outras datas e campos de endereço aqui)
    familiares: List[FamiliarSchema]

@app.post("/cadastrar")
async def cadastrar(dados: ObreiroSchema):
    # Aqui entra a lógica para salvar no Supabase usando a biblioteca 'supabase-py'
    return {"status": "sucesso", "mensagem": f"Obreiro {dados.nome} cadastrado!"}
