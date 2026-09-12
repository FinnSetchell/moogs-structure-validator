"""Shared runtime for the validator: project layout, Minecraft version data,
mcmeta-backed registries, and structure NBT parsing/indexing.

Every check module builds on these. The rule of thumb: anything that reads a
file, fetches from the network, or walks a structure's block list lives here and
runs once per validator run; the checks only apply rules to the result.
"""
