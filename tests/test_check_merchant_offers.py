from __future__ import annotations

from nbtlib import Compound, Int, List, String

from checks import check_merchant_offers as mod
from tests.nbt_helpers import FakeContext, block_entry, build_datapack, entity_entry, save, structure_nbt


def _trader(with_offers: bool = False) -> Compound:
    e = Compound({"id": String("minecraft:wandering_trader")})
    if with_offers:
        e["Offers"] = Compound({"Recipes": List[Compound]([])})
    return e


def _villager(profession: str | None) -> Compound:
    e = Compound({"id": String("minecraft:villager")})
    if profession is not None:
        e["VillagerData"] = Compound({"profession": String(profession), "level": Int(1), "type": String("minecraft:plains")})
    return e


def _run(root, structures, name, entities=None, blocks=None, palette=None):
    save(structure_nbt(4325, entities=entities, blocks=blocks, palette=palette), structures / name)
    return mod.run(FakeContext("test", ["1.21.5"], root))


def test_trader_without_offers_warns(tmp_path, capsys):
    root, structures, _ = build_datapack(tmp_path)
    passed, summary = _run(root, structures, "cart.nbt", [entity_entry(_trader())])
    assert passed
    assert summary == "1 of 1 merchant(s) without saved trades"
    assert "[WARN] cart.nbt: entities[0] minecraft:wandering_trader" in capsys.readouterr().out


def test_trader_with_offers_is_clean(tmp_path, capsys):
    root, structures, _ = build_datapack(tmp_path)
    passed, summary = _run(root, structures, "cart.nbt", [entity_entry(_trader(with_offers=True))])
    assert passed
    assert summary == "1 merchants with saved trades"
    assert "[WARN]" not in capsys.readouterr().out


def test_villager_profession_gates_the_warning(tmp_path, capsys):
    root, structures, _ = build_datapack(tmp_path)
    passed, summary = _run(root, structures, "house.nbt", [
        entity_entry(_villager("minecraft:cartographer")),
        entity_entry(_villager("minecraft:none")),
        entity_entry(_villager("minecraft:nitwit")),
        entity_entry(_villager(None)),
    ])
    assert passed
    assert summary == "1 of 1 merchant(s) without saved trades"
    out = capsys.readouterr().out
    assert "entities[0] minecraft:villager" in out
    assert "entities[1]" not in out and "entities[3]" not in out


def test_rider_trader_is_found(tmp_path, capsys):
    root, structures, _ = build_datapack(tmp_path)
    cart = Compound({"id": String("minecraft:minecart"), "Passengers": List[Compound]([_trader()])})
    passed, summary = _run(root, structures, "rail.nbt", [entity_entry(cart)])
    assert passed
    assert "entities[0].Passengers[0] minecraft:wandering_trader" in capsys.readouterr().out


def test_spawner_trader_is_ignored(tmp_path, capsys):
    root, structures, _ = build_datapack(tmp_path)
    palette = [Compound({"Name": String("minecraft:air")}), Compound({"Name": String("minecraft:spawner")})]
    spawner = Compound({"id": String("minecraft:mob_spawner"), "SpawnData": Compound({"entity": _trader()})})
    passed, summary = _run(root, structures, "trap.nbt", blocks=[block_entry(1, nbt=spawner)], palette=palette)
    assert passed
    assert summary == "no merchants"
    assert "[WARN]" not in capsys.readouterr().out


def test_no_structures_passes(tmp_path):
    passed, summary = mod.run(FakeContext("test", ["1.21.5"], tmp_path))
    assert passed
    assert summary == "no merchants"
