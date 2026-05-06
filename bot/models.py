"""LocalLens domain models. Pure dataclasses with `from_dict` constructors and enum validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


HALAL_STATUSES = frozenset({"halal_certified", "muslim_friendly", "non_halal", "unknown"})

MEAL_TAGS = frozenset({"breakfast", "lunch", "afternoon_snack", "dinner", "late_night"})

# Combined: spec states (new, location_set, chatting, package_offered, accepted,
# follow_up_pending, paid) plus Phase 3 onboarding states.
SESSION_STATES = frozenset(
    {
        "new",
        "awaiting_location",
        "awaiting_dietary",
        "awaiting_intent",
        "location_set",
        "chatting",
        "package_offered",
        "accepted",
        "follow_up_pending",
        "paid",
    }
)

DIETARY_SOURCES = frozenset({"asked", "inferred", "default"})

PACKAGE_TIERS = frozenset({"free", "premium"})

TIME_OF_DAY_WINDOWS = frozenset(
    {"breakfast", "lunch", "afternoon_snack", "dinner", "late_night", "between"}
)


def _require_enum(value: str, allowed: frozenset[str], field_name: str) -> str:
    if value not in allowed:
        raise ValueError(
            f"Invalid {field_name}: {value!r}. Expected one of {sorted(allowed)}."
        )
    return value


def _require_enum_list(values: list[str], allowed: frozenset[str], field_name: str) -> list[str]:
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError(
            f"Invalid {field_name} entries: {bad}. Expected subset of {sorted(allowed)}."
        )
    return list(values)


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    lat: float
    lng: float
    area: str
    cuisine: str
    price_tier: str
    meal_tags: list[str]
    indoor: bool
    vibe_tags: list[str]
    halal_status: str
    insider_tip: str
    google_maps_link: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Restaurant":
        return cls(
            id=d["id"],
            name=d["name"],
            lat=float(d["lat"]),
            lng=float(d["lng"]),
            area=d["area"],
            cuisine=d["cuisine"],
            price_tier=d["price_tier"],
            meal_tags=_require_enum_list(list(d["meal_tags"]), MEAL_TAGS, "meal_tags"),
            indoor=bool(d["indoor"]),
            vibe_tags=list(d["vibe_tags"]),
            halal_status=_require_enum(d["halal_status"], HALAL_STATUSES, "halal_status"),
            insider_tip=d["insider_tip"],
            google_maps_link=d["google_maps_link"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    lat: float
    lng: float
    area: str
    type: str
    tags: list[str]
    best_time: list[str]
    avg_time_minutes: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Location":
        return cls(
            id=d["id"],
            name=d["name"],
            lat=float(d["lat"]),
            lng=float(d["lng"]),
            area=d["area"],
            type=d["type"],
            tags=list(d["tags"]),
            best_time=list(d["best_time"]),
            avg_time_minutes=int(d["avg_time_minutes"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PackageStep:
    order: int
    place_name: str
    place_location: dict[str, float]
    duration_minutes: int
    description: str
    insider_tip: str
    google_maps_link: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PackageStep":
        loc = d["place_location"]
        return cls(
            order=int(d["order"]),
            place_name=d["place_name"],
            place_location={"lat": float(loc["lat"]), "lng": float(loc["lng"])},
            duration_minutes=int(d["duration_minutes"]),
            description=d["description"],
            insider_tip=d["insider_tip"],
            google_maps_link=d["google_maps_link"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Package:
    id: str
    name: str
    tier: str
    price_rm: int | None
    duration_minutes: int
    location_center: dict[str, Any]
    radius_km: float
    intent_tags: list[str]
    weather_tags: dict[str, list[str]]
    indoor_percentage: int
    time_of_day: list[str]
    steps: list[PackageStep]
    why_it_works: str
    upsells: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Package":
        center = d["location_center"]
        weather = d["weather_tags"]
        return cls(
            id=d["id"],
            name=d["name"],
            tier=_require_enum(d["tier"], PACKAGE_TIERS, "tier"),
            price_rm=None if d.get("price_rm") is None else int(d["price_rm"]),
            duration_minutes=int(d["duration_minutes"]),
            location_center={
                "lat": float(center["lat"]),
                "lng": float(center["lng"]),
                "name": center["name"],
            },
            radius_km=float(d["radius_km"]),
            intent_tags=list(d["intent_tags"]),
            weather_tags={
                "ideal": list(weather.get("ideal", [])),
                "ok": list(weather.get("ok", [])),
                "avoid": list(weather.get("avoid", [])),
            },
            indoor_percentage=int(d["indoor_percentage"]),
            time_of_day=list(d["time_of_day"]),
            steps=[PackageStep.from_dict(s) for s in d["steps"]],
            why_it_works=d["why_it_works"],
            upsells=list(d.get("upsells", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DietaryPref:
    halal_only: bool = False
    source: str = "default"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DietaryPref":
        return cls(
            halal_only=bool(d.get("halal_only", False)),
            source=_require_enum(d.get("source", "default"), DIETARY_SOURCES, "dietary.source"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    telegram_user_id: str
    current_state: str = "new"
    location: dict[str, float] | None = None
    dietary: DietaryPref = field(default_factory=DietaryPref)
    active_package_id: str | None = None
    commitment_price: int | None = None
    accepted_at: str | None = None
    follow_up_at: str | None = None
    follow_up_sent_at: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_enum(self.current_state, SESSION_STATES, "current_state")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Session":
        loc_raw = d.get("location")
        location = None
        if loc_raw is not None:
            location = {"lat": float(loc_raw["lat"]), "lng": float(loc_raw["lng"])}
        dietary = (
            DietaryPref.from_dict(d["dietary"]) if "dietary" in d and d["dietary"] is not None else DietaryPref()
        )
        return cls(
            telegram_user_id=str(d["telegram_user_id"]),
            current_state=_require_enum(
                d.get("current_state", "new"), SESSION_STATES, "current_state"
            ),
            location=location,
            dietary=dietary,
            active_package_id=d.get("active_package_id"),
            commitment_price=None if d.get("commitment_price") is None else int(d["commitment_price"]),
            accepted_at=d.get("accepted_at"),
            follow_up_at=d.get("follow_up_at"),
            follow_up_sent_at=d.get("follow_up_sent_at"),
            history=list(d.get("history", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegram_user_id": self.telegram_user_id,
            "current_state": self.current_state,
            "location": dict(self.location) if self.location is not None else None,
            "dietary": self.dietary.to_dict(),
            "active_package_id": self.active_package_id,
            "commitment_price": self.commitment_price,
            "accepted_at": self.accepted_at,
            "follow_up_at": self.follow_up_at,
            "follow_up_sent_at": self.follow_up_sent_at,
            "history": list(self.history),
        }


@dataclass(frozen=True)
class Weather:
    condition: str
    description: str
    temp_c: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Weather":
        return cls(
            condition=str(d["condition"]).lower(),
            description=str(d["description"]),
            temp_c=float(d["temp_c"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Context:
    lat: float
    lng: float
    area_name: str
    weather: Weather
    time_of_day_window: str

    def __post_init__(self) -> None:
        _require_enum(self.time_of_day_window, TIME_OF_DAY_WINDOWS, "time_of_day_window")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Context":
        return cls(
            lat=float(d["lat"]),
            lng=float(d["lng"]),
            area_name=str(d["area_name"]),
            weather=Weather.from_dict(d["weather"]),
            time_of_day_window=_require_enum(
                d["time_of_day_window"], TIME_OF_DAY_WINDOWS, "time_of_day_window"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lng": self.lng,
            "area_name": self.area_name,
            "weather": self.weather.to_dict(),
            "time_of_day_window": self.time_of_day_window,
        }
