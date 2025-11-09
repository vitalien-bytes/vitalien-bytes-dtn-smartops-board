import os, secrets
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from database import SessionLocal, engine
from models import Base, Board, Column, Card

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "dtn2025")
BOARD_TITLE = os.getenv("BOARD_TITLE", "DTN – SmartOps")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Crée les tables au démarrage
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_auth(request: Request):
    if request.session.get("auth") != True:
        raise HTTPException(status_code=401)

@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    # récupère ou crée le board par défaut
    board = db.execute(select(Board)).scalar()
    if not board:
        board = Board(title=BOARD_TITLE)
        # colonnes par défaut
        todo = Column(title="À faire", position=0, board=board)
        doing = Column(title="En cours", position=1, board=board)
        done = Column(title="Terminé", position=2, board=board)
        db.add_all([board, todo, doing, done])
        db.commit()
        db.refresh(board)
    return RedirectResponse(url=f"/board/{board.id}", status_code=302)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["auth"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Identifiants invalides"})

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

@app.get("/board/{board_id}", response_class=HTMLResponse)
def board_view(board_id: int, request: Request, db: Session = Depends(get_db)):
    if request.session.get("auth") != True:
        return RedirectResponse("/login", status_code=302)

    board = db.get(Board, board_id)
    if not board:
        raise HTTPException(404, "Board introuvable")
    return templates.TemplateResponse(
        "board.html",
        {"request": request, "board": board}
    )

# ===== API =====

@app.post("/api/column")
def create_column(request: Request, title: str = Form(...), board_id: int = Form(...), db: Session = Depends(get_db)):
    require_auth(request)
    max_pos = db.scalar(select(func.coalesce(func.max(Column.position), -1)).where(Column.board_id==board_id)) or -1
    col = Column(title=title, position=max_pos+1, board_id=board_id)
    db.add(col); db.commit(); db.refresh(col)
    return {"id": col.id, "title": col.title, "position": col.position}

@app.post("/api/card")
def create_card(request: Request, title: str = Form(...), column_id: int = Form(...), db: Session = Depends(get_db)):
    require_auth(request)
    max_pos = db.scalar(select(func.coalesce(func.max(Card.position), -1)).where(Card.column_id==column_id)) or -1
    card = Card(title=title, position=max_pos+1, column_id=column_id)
    db.add(card); db.commit(); db.refresh(card)
    return {"id": card.id, "title": card.title, "position": card.position}

@app.post("/api/card/move")
def move_card(request: Request, card_id: int = Form(...), to_column: int = Form(...), to_position: int = Form(...), db: Session = Depends(get_db)):
    require_auth(request)
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Carte introuvable")

    # Compacter positions dans l'ancienne colonne
    old_col = card.column_id
    siblings = db.scalars(select(Card).where(Card.column_id==old_col).order_by(Card.position)).all()
    for i, c in enumerate([c for c in siblings if c.id != card.id]):
        c.position = i

    # Insérer dans la nouvelle colonne
    targets = db.scalars(select(Card).where(Card.column_id==to_column).order_by(Card.position)).all()
    to_position = max(0, min(int(to_position), len(targets)))
    for i, c in enumerate(targets):
        c.position = i + (1 if i >= to_position else 0)

    card.column_id = to_column
    card.position = to_position
    db.commit()
    return {"ok": True}
