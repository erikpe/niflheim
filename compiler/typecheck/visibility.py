from __future__ import annotations

from compiler.common.span import SourceSpan
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import ClassInfo, TypeCheckError
from compiler.typecheck.relations import canonicalize_reference_type_name


def require_member_visible(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    owner_type_name: str,
    member_name: str,
    member_kind: str,
    span: SourceSpan,
) -> None:
    is_private = (
        member_name in class_info.private_fields
        if member_kind == "field"
        else member_name in class_info.private_methods
    )
    if not is_private:
        return

    owner_canonical = canonicalize_reference_type_name(ctx, owner_type_name)
    if ctx.current_private_owner_type == owner_canonical:
        return

    raise TypeCheckError(f"Member '{class_info.name}.{member_name}' is private", span)
