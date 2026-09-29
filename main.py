"""Lugar.ph: jeepney directions for Philippine cities, one page per city."""

from __future__ import annotations

import json
import math
import os
import secrets
from hashlib import pbkdf2_hmac, sha256
from pathlib import Path
from threading import Lock
from time import monotonic, time
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from models import ProposalVote, RouteAdminSession, RouteComment, RouteProposal, SessionLocal
from osm_services import search_places, walking_matrix, walking_route
from route_catalog import ROUTE_BY_ID, distance_km, public_catalog
from transit_network import CITY_METADATA, LINES_BY_CITY, landmarks, plan_trips, public_network, trip_help


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Lugar.ph", version="0.3.0")
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
_comment_times: dict[str, float] = {}
_comment_lock = Lock()
_proposal_times: dict[str, float] = {}
_proposal_lock = Lock()
_login_attempts: dict[str, list[float]] = {}
_login_lock = Lock()
ADMIN_COOKIE = "lugar_admin_session"
ADMIN_SESSION_SECONDS = 8 * 60 * 60


class CommentInput(BaseModel):
    author: str = Field(min_length=2, max_length=40)
    body: str = Field(min_length=10, max_length=600)
    website: str = ""  # Quiet honeypot for simple automated form submissions.


class ProposalInput(BaseModel):
    city: str
    kind: str
    route_slug: str | None = None
    number: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=3, max_length=160)
    mode: str = "jeepney"
    coordinates: list[list[float]] = Field(min_length=2, max_length=3000)
    author: str = Field(min_length=2, max_length=40)
    reason: str = Field(min_length=20, max_length=2000)
    source_url: str | None = Field(default=None, max_length=500)
    website: str = ""


class ReviewInput(BaseModel):
    status: str
    note: str = Field(min_length=10, max_length=1000)


class AdminLoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


def _admin_configured() -> bool:
    return bool(os.getenv("ROUTE_ADMIN_USERNAME") and os.getenv("ROUTE_ADMIN_PASSWORD_HASH"))


def _verify_admin_password(password: str) -> bool:
    try:
        scheme, rounds, salt, expected = os.environ["ROUTE_ADMIN_PASSWORD_HASH"].split("$")
        if scheme != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return secrets.compare_digest(actual, bytes.fromhex(expected))
    except (KeyError, ValueError):
        return False


def _admin_username(request: Request) -> str | None:
    token = request.cookies.get(ADMIN_COOKIE, "")
    if len(token) != 43 or not all(char.isalnum() or char in "-_" for char in token):
        return None
    token_hash = sha256(token.encode()).hexdigest()
    with SessionLocal() as session:
        record = session.get(RouteAdminSession, token_hash)
        if not record:
            return None
        if record.expires_at <= int(time()) or record.username != os.getenv("ROUTE_ADMIN_USERNAME"):
            session.delete(record)
            session.commit()
            return None
        return record.username


def _require_admin(request: Request) -> str:
    username = _admin_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Admin sign-in required")
    return username


def _require_same_origin(request: Request) -> None:
    origin = urlparse(request.headers.get("origin", ""))
    if origin.scheme not in {"http", "https"} or origin.netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Invalid request origin")


def _known_line(route_slug: str) -> None:
    if route_slug not in ROUTE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown jeepney line")


def _known_city(city: str) -> str:
    city = city.lower().strip()
    if city not in CITY_METADATA:
        raise HTTPException(status_code=404, detail="Unknown city")
    return city


def _comment_json(comment: RouteComment) -> dict:
    return {
        "id": comment.id,
        "route_slug": comment.route_slug,
        "author": comment.author,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
    }


def _proposal_json(proposal: RouteProposal, votes: int = 0, voted: bool = False) -> dict:
    return {
        "id": proposal.id, "city": proposal.city, "kind": proposal.kind,
        "route_slug": proposal.route_slug, "number": proposal.number, "name": proposal.name,
        "mode": proposal.mode, "coordinates": json.loads(proposal.coordinates_json),
        "author": proposal.author, "reason": proposal.reason, "source_url": proposal.source_url,
        "status": proposal.status, "review_note": proposal.review_note,
        "created_at": proposal.created_at.isoformat(), "votes": votes, "voted": voted,
    }


def _voter_id(request: Request, response: Response) -> str:
    voter = request.cookies.get("lugar_voter")
    if voter and len(voter) == 43 and all(char.isalnum() or char in "-_" for char in voter):
        return voter
    voter = secrets.token_urlsafe(32)
    response.set_cookie("lugar_voter", voter, max_age=31536000, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return voter


def _proposal_counts(session, proposal_ids: list[int], voter: str) -> tuple[dict[int, int], set[int]]:
    if not proposal_ids:
        return {}, set()
    counts = dict(session.execute(
        select(ProposalVote.proposal_id, func.count(ProposalVote.id))
        .where(ProposalVote.proposal_id.in_(proposal_ids))
        .group_by(ProposalVote.proposal_id)
    ).all())
    voted = set(session.scalars(
        select(ProposalVote.proposal_id)
        .where(ProposalVote.proposal_id.in_(proposal_ids), ProposalVote.voter_id == voter)
    ).all())
    return counts, voted

# Other spellings of a city's page address, sent on to its canonical one.
CITY_ALIASES = {"cagayan-de-oro": "cdo", "cagayandeoro": "cdo", "cagayan": "cdo", "naga-city": "naga", "davao-city": "davao"}


def _city_list() -> list[dict]:
    return [{"id": city, **metadata, "lines": len(LINES_BY_CITY[city])} for city, metadata in CITY_METADATA.items()]


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Splash page: what Lugar.ph is for, and a city to start in."""
    return templates.TemplateResponse(request=request, name="home.html", context={"cities": _city_list()})


@app.get("/api/cities")
def cities():
    return {"cities": _city_list()}


@app.get("/api/places")
def places(q: str = Query(min_length=2, max_length=120), city: str = "bacolod"):
    """Explicit city-bounded place search through OpenStreetMap Nominatim."""
    city = _known_city(city)
    try:
        return {"results": search_places(city, q)}
    except (OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Place search is temporarily unavailable")


@app.get("/api/landmarks")
def city_landmarks(city: str = "bacolod"):
    """Landmarks along mapped jeepney lines; the client filters these as the rider types."""
    return {"landmarks": landmarks(_known_city(city))}


@app.get("/api/walking-route")
def walking_directions(
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lng: float = Query(ge=-180, le=180),
):
    """Pedestrian directions from a pin to a mapped jeepney corridor."""
    return walking_route(from_lat, from_lng, to_lat, to_lng)


@app.get("/api/jeepney-routes")
def jeepney_routes(city: str = "bacolod"):
    """Published or documented jeepney routes for one supported city."""
    return public_catalog(_known_city(city))


@app.get("/api/jeepney-network", response_class=JSONResponse)
def jeepney_network(city: str = "bacolod"):
    """Road-aligned GeoJSON for a supported city's jeepney corridors."""
    city = _known_city(city)
    return JSONResponse(
        content=public_network(city),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/jeepney-routes/{route_slug}/comments")
def route_comments(route_slug: str):
    _known_line(route_slug)
    with SessionLocal() as session:
        comments = session.scalars(
            select(RouteComment)
            .where(RouteComment.route_slug == route_slug)
            .order_by(RouteComment.created_at.desc(), RouteComment.id.desc())
            .limit(50)
        ).all()
        return {"comments": [_comment_json(comment) for comment in comments]}


@app.post("/api/jeepney-routes/{route_slug}/comments", status_code=201)
def add_route_comment(route_slug: str, payload: CommentInput, request: Request):
    _known_line(route_slug)
    if payload.website:
        raise HTTPException(status_code=422, detail="Invalid comment")
    author = " ".join(payload.author.split())
    body = " ".join(payload.body.split())
    if len(author) < 2 or len(body) < 10:
        raise HTTPException(status_code=422, detail="Please enter a name and a useful comment")
    client = request.client.host if request.client else "unknown"
    now = monotonic()
    with _comment_lock:
        if now - _comment_times.get(client, 0) < 20:
            raise HTTPException(status_code=429, detail="Please wait before commenting again")
        _comment_times[client] = now
        if len(_comment_times) > 1000:
            _comment_times.clear()
    with SessionLocal() as session:
        comment = RouteComment(route_slug=route_slug, author=author, body=body)
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return _comment_json(comment)


@app.get("/api/route-proposals")
def route_proposals(request: Request, response: Response, city: str = "bacolod"):
    city = _known_city(city)
    voter = _voter_id(request, response)
    with SessionLocal() as session:
        proposals = session.scalars(
            select(RouteProposal).where(RouteProposal.city == city)
            .order_by(RouteProposal.created_at.desc(), RouteProposal.id.desc()).limit(200)
        ).all()
        counts, voted = _proposal_counts(session, [item.id for item in proposals], voter)
        return {"proposals": [
            _proposal_json(item, counts.get(item.id, 0), item.id in voted) for item in proposals
        ]}


@app.post("/api/route-proposals", status_code=201)
def add_route_proposal(payload: ProposalInput, request: Request):
    city = _known_city(payload.city)
    if payload.website or payload.kind not in {"correction", "new"} or payload.mode not in {"jeepney", "uv_express"}:
        raise HTTPException(status_code=422, detail="Invalid route proposal")
    route_slug = payload.route_slug if payload.kind == "correction" else None
    if payload.kind == "correction":
        if not route_slug or not any(line.id == route_slug for line in LINES_BY_CITY[city]):
            raise HTTPException(status_code=422, detail="Select a route in this city to correct")
    elif payload.route_slug:
        raise HTTPException(status_code=422, detail="New routes cannot have an existing route ID")
    number, name = payload.number.strip(), " ".join(payload.name.split())
    author, reason = " ".join(payload.author.split()), " ".join(payload.reason.split())
    if not number or len(name) < 3 or len(author) < 2 or len(reason) < 20:
        raise HTTPException(status_code=422, detail="Complete the route name, number, your name, and explanation")
    source_url = (payload.source_url or "").strip() or None
    if source_url:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Evidence link must be an HTTP or HTTPS URL")
    center_lat, center_lng = CITY_METADATA[city]["center"]
    for point in payload.coordinates:
        if len(point) != 2 or not all(math.isfinite(value) for value in point):
            raise HTTPException(status_code=422, detail="Route points must have finite longitude and latitude")
        lng, lat = point
        if not (-180 <= lng <= 180 and -90 <= lat <= 90) or distance_km(center_lat, center_lng, lat, lng) > 80:
            raise HTTPException(status_code=422, detail="Route points must be near the selected city")
    if all(point == payload.coordinates[0] for point in payload.coordinates):
        raise HTTPException(status_code=422, detail="Draw at least two different route points")
    if payload.kind == "correction":
        original = next(feature for feature in public_network(city)["features"] if feature["properties"]["id"] == route_slug)
        props = original["properties"]
        if (number == str(props["number"]) and name == props["name"] and payload.mode == props.get("mode", "jeepney")
                and payload.coordinates == original["geometry"]["coordinates"]):
            raise HTTPException(status_code=422, detail="Change the route details or path before submitting")
    client = request.client.host if request.client else "unknown"
    now = monotonic()
    with _proposal_lock:
        if now - _proposal_times.get(client, 0) < 60:
            raise HTTPException(status_code=429, detail="Please wait before submitting another route")
        _proposal_times[client] = now
        if len(_proposal_times) > 1000:
            _proposal_times.clear()
    with SessionLocal() as session:
        proposal = RouteProposal(
            city=city, kind=payload.kind, route_slug=route_slug, number=number, name=name,
            mode=payload.mode, coordinates_json=json.dumps(payload.coordinates, separators=(",", ":")),
            author=author, reason=reason, source_url=source_url,
        )
        session.add(proposal)
        session.commit()
        session.refresh(proposal)
        return _proposal_json(proposal)


@app.post("/api/route-proposals/{proposal_id}/vote")
def vote_route_proposal(proposal_id: int, request: Request, response: Response):
    voter = _voter_id(request, response)
    with SessionLocal() as session:
        proposal = session.get(RouteProposal, proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Unknown route proposal")
        if proposal.status != "pending":
            raise HTTPException(status_code=409, detail="Voting has closed for this proposal")
        existing = session.scalar(select(ProposalVote).where(
            ProposalVote.proposal_id == proposal_id, ProposalVote.voter_id == voter
        ))
        if existing:
            session.delete(existing)
        else:
            session.add(ProposalVote(proposal_id=proposal_id, voter_id=voter))
        session.commit()
        counts, voted = _proposal_counts(session, [proposal_id], voter)
        return {"votes": counts.get(proposal_id, 0), "voted": proposal_id in voted}


@app.get("/admin/routes", response_class=HTMLResponse)
def route_admin_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_routes.html")


@app.get("/api/admin/session")
def admin_session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"configured": _admin_configured(), "username": _admin_username(request)}


@app.post("/api/admin/login")
def admin_login(payload: AdminLoginInput, request: Request, response: Response):
    _require_same_origin(request)
    if not _admin_configured():
        raise HTTPException(status_code=503, detail="Admin login has not been configured")
    client = request.client.host if request.client else "unknown"
    now = monotonic()
    with _login_lock:
        attempts = [stamp for stamp in _login_attempts.get(client, []) if now - stamp < 300]
        if len(attempts) >= 5:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later")
        _login_attempts[client] = attempts
    username = os.environ["ROUTE_ADMIN_USERNAME"]
    valid_user = secrets.compare_digest(payload.username, username)
    valid_password = _verify_admin_password(payload.password)
    if not (valid_user and valid_password):
        with _login_lock:
            _login_attempts[client].append(now)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    with _login_lock:
        _login_attempts.pop(client, None)
    token = secrets.token_urlsafe(32)
    with SessionLocal() as session:
        session.add(RouteAdminSession(
            token_hash=sha256(token.encode()).hexdigest(), username=username,
            expires_at=int(time()) + ADMIN_SESSION_SECONDS,
        ))
        session.commit()
    response.set_cookie(
        ADMIN_COOKIE, token, max_age=ADMIN_SESSION_SECONDS, httponly=True, samesite="strict",
        secure=bool(os.getenv("VERCEL")) or request.url.scheme == "https", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"username": username}


@app.post("/api/admin/logout")
def admin_logout(request: Request, response: Response):
    _require_same_origin(request)
    token = request.cookies.get(ADMIN_COOKIE, "")
    if token:
        with SessionLocal() as session:
            record = session.get(RouteAdminSession, sha256(token.encode()).hexdigest())
            if record:
                session.delete(record)
                session.commit()
    response.delete_cookie(ADMIN_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"signed_out": True}


@app.get("/api/admin/route-proposals")
def admin_route_proposals(request: Request, response: Response):
    _require_admin(request)
    response.headers["Cache-Control"] = "no-store"
    with SessionLocal() as session:
        proposals = session.scalars(
            select(RouteProposal).order_by(
                case((RouteProposal.status == "pending", 0), else_=1),
                RouteProposal.created_at.desc(), RouteProposal.id.desc(),
            ).limit(500)
        ).all()
        counts, _ = _proposal_counts(session, [item.id for item in proposals], "")
        return {"proposals": [_proposal_json(item, counts.get(item.id, 0)) for item in proposals]}


@app.patch("/api/route-proposals/{proposal_id}/review")
def review_route_proposal(proposal_id: int, payload: ReviewInput, request: Request, x_review_token: str | None = Header(default=None)):
    configured = os.getenv("ROUTE_REVIEW_TOKEN")
    token_valid = bool(configured and x_review_token and secrets.compare_digest(x_review_token, configured))
    if not token_valid:
        _require_admin(request)
        _require_same_origin(request)
    if payload.status not in {"accepted", "rejected"}:
        raise HTTPException(status_code=422, detail="Review status must be accepted or rejected")
    note = " ".join(payload.note.split())
    if len(note) < 10:
        raise HTTPException(status_code=422, detail="Please explain the review decision")
    with SessionLocal() as session:
        proposal = session.get(RouteProposal, proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Unknown route proposal")
        proposal.status = payload.status
        proposal.review_note = note
        session.commit()
        session.refresh(proposal)
        votes = session.scalar(select(func.count(ProposalVote.id)).where(ProposalVote.proposal_id == proposal_id)) or 0
        return _proposal_json(proposal, votes)


@app.get("/api/routes")
def routes(
    origin_lat: float = Query(10.6765, ge=-90, le=90),
    origin_lng: float = Query(122.9509, ge=-180, le=180),
    destination_lat: float = Query(10.6922, ge=-90, le=90),
    destination_lng: float = Query(122.9569, ge=-180, le=180),
    city: str = "bacolod",
):
    """Suggest mapped jeepney connections (up to three rides) plus distinct alternatives."""
    city = _known_city(city)
    straight_km = distance_km(origin_lat, origin_lng, destination_lat, destination_lng)
    itineraries = plan_trips(origin_lat, origin_lng, destination_lat, destination_lng, city, walk_matrix=walking_matrix)
    road_km = itineraries[0]["road_distance_km"] if itineraries else max(0.6, straight_km * 1.35)

    # Future PostGIS integration: store surveyed route geometries, query near
    # both endpoints, and compute exact access, ride, and transfer legs.
    return {
        "city": city,
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "destination": {"lat": destination_lat, "lng": destination_lng},
        "distance_km": round(road_km, 1),
        "jeepney_notice": None if itineraries else "No mapped jeepney connection was found within walking distance of both pins. Try moving a pin closer to a colored corridor or check the jeepney route map.",
        "no_route": None if itineraries else trip_help(origin_lat, origin_lng, destination_lat, destination_lng, city),
        "estimate_note": (
            "Walking links connect your pins to the nearest mapped corridors. Signboards, direction, current service, time, and fare need local confirmation."
            if itineraries else
            "Lugar.ph currently recommends jeepney routes only. Mapped coverage and active service still need local confirmation."
        ),
        "fare_note": FARE_NOTE,
        "options": [_jeepney_option(itinerary, index) for index, itinerary in enumerate(itineraries)],
    }


FARE_NOTE = "Estimated LTFRB regular fare (₱14 for the first 4 km, ₱2 per km after). Students, seniors, and PWDs pay 20% less."


def _jeepney_option(itinerary: dict, index: int) -> dict:
    access = itinerary["access"]
    rides = itinerary["ride_count"]
    if rides == 1:
        description = f"Walk {round((access['origin_walk_km'] + access['destination_walk_km']) * 1000)} m total, then take one jeepney"
    else:
        transfers = "once" if rides == 2 else f"{rides - 1} times"
        description = f"Take {rides} jeepneys and transfer {transfers} ({round(access['transfer_walk_km'] * 1000)} m between lines)"
    return {
        "id": "jeepney" if index == 0 else f"jeepney-alt-{index}",
        "mode": "jeepney",
        "label": "Jeepney",
        "recommended": index == 0,
        "highlight": itinerary["highlight"],
        "tags": itinerary["tags"],
        "compared_to_best": itinerary["compared_to_best"],
        "fare_php": itinerary["fare_php"],
        "duration_minutes": itinerary["duration_minutes"],
        "ride_duration_minutes": itinerary["ride_minutes"],
        "ride_distance_km": itinerary["ride_km"],
        "walk_distance_km": itinerary["walk_km"],
        "distance_km": itinerary["road_distance_km"],
        "description": description,
        "lines": itinerary["lines"],
        "itinerary": itinerary,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# Declared last so it never shadows /api, /health, or the docs pages.
@app.get("/{city}", response_class=HTMLResponse)
def city_page(request: Request, city: str):
    """The trip planner, opened on one city: /bacolod, /cdo, /baguio."""
    wanted = city.lower().strip()
    canonical = CITY_ALIASES.get(wanted, wanted)
    if canonical not in CITY_METADATA:
        return templates.TemplateResponse(request=request, name="home.html", context={"cities": _city_list(), "unknown_city": city}, status_code=404)
    if canonical != city:
        return RedirectResponse(f"/{canonical}", status_code=308)
    return templates.TemplateResponse(request=request, name="index.html", context={"city": canonical, "cities": _city_list()})
