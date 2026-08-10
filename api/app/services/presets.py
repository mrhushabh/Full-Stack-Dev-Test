"""Common job templates.

A field tech does not encounter thirty unrelated jobs a week; they do the same
eight or ten over and over. A failed run capacitor is the single most common
no-cooling call in the trade, and building that estimate from a blank form means
searching a thirty-item catalog for a $32 part, then picking a job type, then a
level, then hours -- every time, several times a day.

Each preset is a starting point, not a lock: it drops in line items the tech then
edits. This is the biggest single reduction in time-on-site in the tool, and it is
also the least clever thing in it.

Note that repair presets include the diagnostic line. Somebody had to find the
fault before replacing the part, that hour is real, and modelling it explicitly is
what makes the "waive the diagnostic when they approve the work" rule mean
anything.

The list below is *seed data*, not the live source. It is imported into the
`presets` table on first run and read from there afterwards, exactly like the
JSON files in `data/` -- so a shop can add or retire a job without a redeploy, and
their edits survive restarts.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import ApiModel, JobType
from app.models.tables import PresetRow
from app.money import plain


class PresetEquipmentLine(ApiModel):
    equipment_id: str
    quantity: int = 1


class PresetLaborLine(ApiModel):
    job_type: JobType
    #: None means "use whatever the inference engine proposes for this customer" --
    #: which is how install presets pick up residential vs commercial vs mini-split
    #: rates without the preset having to know the property.
    level: str | None = None
    hours: Decimal | None = None


class Preset(ApiModel):
    id: str
    name: str
    description: str
    group: str
    equipment: list[PresetEquipmentLine] = []
    labor: list[PresetLaborLine] = []


def _repair(job_type_hours: Decimal, level: str) -> list[PresetLaborLine]:
    """Diagnostic followed by the repair itself -- how the visit actually goes."""
    return [
        PresetLaborLine(job_type=JobType.DIAGNOSTIC, level=None),
        PresetLaborLine(job_type=JobType.REPAIR, level=level, hours=job_type_hours),
    ]


SEED_PRESETS: list[Preset] = [
    # -- Repairs: the bread and butter --------------------------------------
    Preset(
        id="capacitor",
        name="Run capacitor replacement",
        description="The most common no-cooling call. Cheap part, quick swap.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ018")],
        labor=_repair(Decimal("1"), "minor"),
    ),
    Preset(
        id="hard-start",
        name="Hard start kit",
        description="Compressor struggling to start on an ageing system.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ019")],
        labor=_repair(Decimal("1"), "minor"),
    ),
    Preset(
        id="condenser-fan-motor",
        name="Condenser fan motor",
        description="Outdoor unit running but not moving air.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ013")],
        labor=_repair(Decimal("1.5"), "minor"),
    ),
    Preset(
        id="blower-motor",
        name="Blower motor (PSC)",
        description="No airflow at the registers; standard indoor blower.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ012")],
        labor=_repair(Decimal("2"), "minor"),
    ),
    Preset(
        id="ecm-blower-motor",
        name="ECM blower motor",
        description="Variable-speed blower failure. Pricier part, longer job.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ029")],
        labor=_repair(Decimal("3"), "major"),
    ),
    Preset(
        id="ignitor",
        name="Furnace ignitor",
        description="No heat, furnace not lighting.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ023")],
        labor=_repair(Decimal("1"), "minor"),
    ),
    Preset(
        id="control-board",
        name="Furnace control board",
        description="Intermittent or dead furnace control.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ022")],
        labor=_repair(Decimal("1.5"), "minor"),
    ),
    Preset(
        id="gas-valve",
        name="Gas valve replacement",
        description="Furnace not firing; valve failed closed.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ020")],
        labor=_repair(Decimal("2"), "minor"),
    ),
    Preset(
        id="compressor",
        name="Compressor replacement",
        description="Major refrigerant-circuit job. Recovery, brazing, recharge.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ011")],
        labor=_repair(Decimal("4"), "major"),
    ),
    Preset(
        id="evap-coil",
        name="Evaporator coil replacement",
        description="Leaking indoor coil.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ014")],
        labor=_repair(Decimal("4"), "major"),
    ),
    Preset(
        id="thermostat",
        name="Thermostat replacement",
        description="Standard programmable replacement.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ016")],
        labor=_repair(Decimal("1"), "minor"),
    ),
    Preset(
        id="smart-thermostat",
        name="Smart thermostat upgrade",
        description="Customer-requested upgrade; common add-on sale.",
        group="repair",
        equipment=[PresetEquipmentLine(equipment_id="EQ017")],
        labor=_repair(Decimal("1.5"), "minor"),
    ),
    # -- Installs -----------------------------------------------------------
    Preset(
        id="ac-replacement",
        name="AC system replacement",
        description="Full condenser replacement. Level follows the property.",
        group="install",
        equipment=[PresetEquipmentLine(equipment_id="EQ009")],
        labor=[PresetLaborLine(job_type=JobType.INSTALL, level=None)],
    ),
    Preset(
        id="furnace-replacement",
        name="Furnace replacement",
        description="Gas furnace changeout.",
        group="install",
        equipment=[PresetEquipmentLine(equipment_id="EQ010")],
        labor=[PresetLaborLine(job_type=JobType.INSTALL, level=None)],
    ),
    Preset(
        id="heat-pump-replacement",
        name="Heat pump replacement",
        description="Heat pump changeout.",
        group="install",
        equipment=[PresetEquipmentLine(equipment_id="EQ002")],
        labor=[PresetLaborLine(job_type=JobType.INSTALL, level=None)],
    ),
    Preset(
        id="mini-split-install",
        name="Mini-split install",
        description="Single-zone ductless install.",
        group="install",
        equipment=[PresetEquipmentLine(equipment_id="EQ005")],
        labor=[PresetLaborLine(job_type=JobType.INSTALL, level="mini-split")],
    ),
    # -- Service ------------------------------------------------------------
    Preset(
        id="maintenance",
        name="Seasonal maintenance",
        description="Routine tune-up. Level follows the property.",
        group="maintenance",
        equipment=[],
        labor=[PresetLaborLine(job_type=JobType.MAINTENANCE, level=None)],
    ),
    Preset(
        id="diagnostic",
        name="Diagnostic visit only",
        description="Fault-finding with no work authorised yet.",
        group="diagnostic",
        equipment=[],
        labor=[PresetLaborLine(job_type=JobType.DIAGNOSTIC, level=None)],
    ),
]

SEED_PRESETS_BY_ID = {p.id: p for p in SEED_PRESETS}


# ---------------------------------------------------------------------------
# Reading the live presets
# ---------------------------------------------------------------------------


def _to_preset(row: PresetRow) -> Preset:
    return Preset(
        id=row.id,
        name=row.name,
        description=row.description,
        group=row.group_name,
        equipment=[
            PresetEquipmentLine(equipment_id=e.equipment_id, quantity=e.quantity)
            for e in row.equipment
        ],
        labor=[
            PresetLaborLine(
                job_type=l.job_type,
                level=l.level,
                hours=plain(l.hours) if l.hours is not None else None,
            )
            for l in row.labor
        ],
    )


def list_presets(session: Session) -> list[Preset]:
    rows = session.scalars(
        select(PresetRow).order_by(PresetRow.sort_order, PresetRow.id)
    )
    return [_to_preset(row) for row in rows]


def preset_by_id(session: Session, preset_id: str) -> Preset | None:
    row = session.get(PresetRow, preset_id)
    return _to_preset(row) if row else None
