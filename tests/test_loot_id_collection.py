from checks.check_registries import _collect_ids


def test_item_entry():
    data = {"pools": [{"entries": [{"type": "minecraft:item", "name": "minecraft:diamond"}]}]}
    items, blocks = set(), set()
    _collect_ids(data, items, blocks)
    assert "minecraft:diamond" in items


def test_set_contents_nested_entries():
    data = {"functions": [{"function": "minecraft:set_contents", "entries": [
        {"type": "minecraft:item", "name": "minecraft:cooked_beef"},
    ]}]}
    items, blocks = set(), set()
    _collect_ids(data, items, blocks)
    assert "minecraft:cooked_beef" in items


def test_give_item_direct_id():
    data = {"function": "minecraft:give_item", "item": {"id": "minecraft:apple"}}
    items, blocks = set(), set()
    _collect_ids(data, items, blocks)
    assert "minecraft:apple" in items


def test_give_item_string_form():
    data = {"function": "minecraft:give_item", "item": "minecraft:bread"}
    items, blocks = set(), set()
    _collect_ids(data, items, blocks)
    assert "minecraft:bread" in items


def test_block_state_property_condition():
    data = {"conditions": [{"condition": "minecraft:block_state_property", "block": "minecraft:crimson_stem"}]}
    items, blocks = set(), set()
    _collect_ids(data, items, blocks)
    assert "minecraft:crimson_stem" in blocks
