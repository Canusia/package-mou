"""MOUs sidebar item (cis.menu_registry); right after `all_highschools` (10)
in ce `highschools`. On a cis without the registry nothing registers.
"""
try:
    from cis.menu_registry import menu
except ImportError:   # cis without the registry: the menu migrations still apply
    menu = None

if menu is not None:
    menu.register('ce', 'mous', 'MOUs', url='mou_ce:all', parent='highschools',
                  order=15)
