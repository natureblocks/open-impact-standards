import re
from validation import patterns


class FieldTypeDetails:
    def __init__(self, is_list, item_type, item_tag):
        self.is_list = is_list
        self.item_type = item_type
        self.item_tag = item_tag

    def to_string(self, specify_object_tag=False):
        item_type_string = self.item_type if self.item_type is not None else "NULL"

        if specify_object_tag and item_type_string == "OBJECT":
            item_type_string = "EDGE"

        if self.is_list:
            if item_type_string == "EDGE":
                return "EDGE_COLLECTION"
            elif re.match(patterns.global_ref, item_type_string):
                return f"[{item_type_string}]"

            return (
                f"{item_type_string}_LIST" if item_type_string is not "NULL" else "LIST"
            )

        return item_type_string
