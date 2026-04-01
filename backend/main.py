from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Session, create_engine, Field, Relationship
from typing import List, Optional
from datetime import date
import os

# 1. Configuração do Banco de Dados
DATABASE_URL = os.getenv("DATABASE_URL")

# Correção automática para o driver do SQLAlchemy
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

app = FastAPI()

# 2. Configuração de CORS (Essencial para o PWA salvar)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Modelos de Dados (Tabelas)
class Familiar(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    tipo_parentesco: str
    data_nascimento: Optional[date] = None
    obreiro_id: Optional[int] = Field(default=None, foreign_key="obreiro.id")

class Obreiro(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    cim: str = Field(unique=True)
    cpf: str = Field(unique=True)
    data_nascimento: Optional[date] = None
    # Datas Maçônicas
    data_iniciacao: Optional[date] = None
    data_elevacao: Optional[date] = None
    data_exaltacao: Optional[date] = None
    data_filiacao: Optional[date] = None
    data_afastamento: Optional[date] = None
    # Endereço
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    
    # Relacionamento com familiares
    familiares: List[Familiar] = Relationship(sa_relationship_kwargs={"cascade": "all, delete-orphan"})

# 4. Criar tabelas no startup
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

# 5. Rota de Cadastro (Onde a mágica acontece)
@app.post("/cadastrar")
async def cadastrar(dados: Obreiro):
    with Session(engine) as session:
        try:
            session.add(dados)
            session.commit()
            session.refresh(dados)
            return {"status": "sucesso", "mensagem": f"Obreiro {dados.nome} cadastrado com ID {dados.id}!"}
        except Exception as e:
            session.rollback()
            # Se der erro (ex: CIM ou CPF já existente), avisa o app
            raise HTTPException(status_code=400, detail=str(e))
