import re
from validation import patterns


class TypeDetails:
    def __init__(self, is_list, item_type, object_type_ref):
        self.is_list = is_list
        self.item_type = item_type
        self.object_type_ref = object_type_ref

    def to_field_type_string(self):
        item_type = self.item_type if self.item_type is not None else "NULL"

        if self.is_list:
            return f"{item_type}_LIST" if item_type is not "NULL" else "LIST"

        return item_type

    def to_string(self):
        item_type_string = self.item_type if self.item_type is not None else "NULL"

        if self.is_list:
            if re.match(patterns.global_alias_ref, item_type_string) or re.match(
                patterns.global_id_ref, item_type_string
            ):
                return f"[{item_type_string}]"

            return (
                f"{item_type_string}_LIST" if item_type_string is not "NULL" else "LIST"
            )

        return item_type_string

    def matches_type(self, field_type_details):
        return (
            self.is_list == field_type_details.is_list
            and self.item_type == field_type_details.item_type
            and self.object_type_ref == field_type_details.object_type_ref
        )
