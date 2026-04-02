from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Session, create_engine, Field, Relationship, select, or_
from typing import List, Optional
from datetime import date
import os

# 1. Configuração do Banco de Dados
DATABASE_URL = os.getenv("DATABASE_URL")

# Correção para o driver do SQLAlchemy caso comece com postgres://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Adicionado pool_pre_ping=True para evitar erros de conexão inativa
engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,
    pool_recycle=300
)

app = FastAPI()

# 2. Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Modelos de Dados
class Familiar(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    tipo_parentesco: str
    data_nascimento: Optional[date] = None
    obreiro_id: Optional[int] = Field(default=None, foreign_key="obreiro.id")
    obreiro: Optional["Obreiro"] = Relationship(back_populates="familiares")

class Obreiro(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    cim: str = Field(unique=True)
    cpf: str = Field(unique=True)
    data_nascimento: Optional[date] = None
    data_iniciacao: Optional[date] = None
    data_elevacao: Optional[date] = None
    data_exaltacao: Optional[date] = None
    data_filiacao: Optional[date] = None
    data_afastamento: Optional[date] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    
    familiares: List[Familiar] = Relationship(back_populates="obreiro", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

# 3.1 Modelos de Criação (Schemas de Entrada para o FastAPI)
class FamiliarCreate(SQLModel):
    nome: str
    tipo_parentesco: str
    data_nascimento: Optional[date] = None

class ObreiroCreate(SQLModel):
    nome: str
    cim: str
    cpf: str
    data_nascimento: Optional[date] = None
    data_iniciacao: Optional[date] = None
    data_elevacao: Optional[date] = None
    data_exaltacao: Optional[date] = None
    data_filiacao: Optional[date] = None
    data_afastamento: Optional[date] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    estado: Optional[str] = None
    familiares: List[FamiliarCreate] = []

# 4. Criar tabelas no startup
@app.on_event("startup")
def on_startup():
    try:
        SQLModel.metadata.create_all(engine)
    except Exception as e:
        print(f"Erro ao criar tabelas: {e}")

# 5. Rota de Cadastro
@app.post("/cadastrar")
async def cadastrar(dados: ObreiroCreate):
    with Session(engine) as session:
        try:
            # Verifica se o obreiro já existe pelo CPF OU pelo CIM
            statement = select(Obreiro).where(or_(Obreiro.cpf == dados.cpf, Obreiro.cim == dados.cim))
            db_obreiros = session.exec(statement).all()
            
            if len(db_obreiros) > 1:
                raise ValueError("Conflito: O CPF e o CIM informados pertencem a pessoas diferentes no banco.")
                
            db_obreiro = db_obreiros[0] if db_obreiros else None
            
            # Pydantic V1/V2 compatibility (converte para dicionário ignorando familiares por enquanto)
            dados_dict = dados.model_dump(exclude={"familiares"}) if hasattr(dados, "model_dump") else dados.dict(exclude={"familiares"})
            
            if db_obreiro:
                # Atualiza os campos do obreiro existente
                for key, value in dados_dict.items():
                    setattr(db_obreiro, key, value)
                # Limpa familiares antigos para recriar (o cascade delete-orphan cuida da exclusão no banco)
                db_obreiro.familiares.clear()
                acao = "atualizado"
            else:
                # Cria um novo obreiro
                db_obreiro = Obreiro(**dados_dict)
                acao = "cadastrado"
            
            # Vincula e adiciona os familiares adequadamente na instância do banco
            for fam_dados in dados.familiares:
                fam_dict = fam_dados.model_dump() if hasattr(fam_dados, "model_dump") else fam_dados.dict()
                db_obreiro.familiares.append(Familiar(**fam_dict))
                
            session.add(db_obreiro)
            session.commit()
            session.refresh(db_obreiro)
            return {"status": "sucesso", "mensagem": f"Obreiro {db_obreiro.nome} {acao} com sucesso!"}
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=400, detail=f"Erro ao salvar: {str(e)}")

# 6. Rota de Busca por CIM
@app.get("/obreiros/{cim}")
async def buscar_obreiro(cim: str):
    with Session(engine) as session:
        try:
            statement = select(Obreiro).where(Obreiro.cim == cim.strip())
            db_obreiro = session.exec(statement).first()
            
            if not db_obreiro:
                raise HTTPException(status_code=404, detail="Obreiro não encontrado.")
            
            # Prepara os dados convertendo em um dicionário para a API enviar (incluindo familiares)
            resultado = db_obreiro.model_dump() if hasattr(db_obreiro, "model_dump") else db_obreiro.dict()
            resultado["familiares"] = [fam.model_dump() if hasattr(fam, "model_dump") else fam.dict() for fam in db_obreiro.familiares]
            
            return resultado
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro interno ao buscar: {str(e)}")
