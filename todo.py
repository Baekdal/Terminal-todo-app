#!/usr/bin/env python3
import curses
import json
import os
import textwrap
import uuid
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TODO_FILE = os.path.join(SCRIPT_DIR, 'todos.json')

def load_todos():
    if os.path.exists(TODO_FILE):
        with open(TODO_FILE, 'r') as f:
            todos = json.load(f)
            # Ensure all todos have IDs (for backwards compatibility)
            for todo in todos:
                if 'id' not in todo:
                    todo['id'] = str(uuid.uuid4())
            return todos
    return []

def get_file_mtime():
    """Get file modification time, or 0 if file doesn't exist"""
    if os.path.exists(TODO_FILE):
        return os.path.getmtime(TODO_FILE)
    return 0

def save_todos(todos):
    """Save todos with merge protection - keeps items added by other sessions"""
    # Load current file to check for items added by other sessions
    current_todos = load_todos()
    
    # Find items in current file that aren't in our list (added by other session)
    # Compare by ID instead of task text
    our_ids = {todo['id'] for todo in todos if 'id' in todo}
    new_items = [todo for todo in current_todos if todo.get('id') not in our_ids]
    
    # Merge: our todos + new items from other sessions
    merged = todos + new_items
    
    # Sort by group for consistent display order
    def get_sort_key(todo):
        task = todo['task']
        # Remove priority prefix for sorting
        if task.startswith('!! '):
            task = task[3:]
        elif task.startswith('! '):
            task = task[2:]
        
        # Extract group prefix (text before colon)
        if ':' in task:
            group = task.split(':', 1)[0].strip()
            suffix = task.split(':', 1)[1].strip()
            # Sort by: group name, then task within group
            return (0, group.lower(), suffix.lower())
        else:
            # Ungrouped items sort last
            return (1, '', task.lower())
    
    merged.sort(key=get_sort_key)
    
    with open(TODO_FILE, 'w') as f:
        json.dump(merged, f, indent=2)

def get_todo_group(todo):
    """Get the group name for a todo item"""
    task = todo['task']
    # Remove priority prefix
    if task.startswith('!! '):
        task = task[3:]
    elif task.startswith('! '):
        task = task[2:]
    
    # Extract group prefix (text before colon)
    if ':' in task:
        return task.split(':', 1)[0].strip()
    return '__ungrouped__'

def build_selectable_items(todos, collapsed_groups, hide_completed=False):
    """Build list of selectable items (group headers + visible todos)
    Returns list of tuples: ('group', group_name) or ('todo', todo_index)
    """
    items = []
    groups = {}
    group_order = []
    
    for i, todo in enumerate(todos):
        # Skip completed items if hide_completed is enabled
        if hide_completed and todo.get('done', False):
            continue
            
        task = todo['task']
        # Extract priority first
        priority = 0
        clean_task = task
        if task.startswith('!! '):
            priority = 2
            clean_task = task[3:]
        elif task.startswith('! '):
            priority = 1
            clean_task = task[2:]
        
        if ':' in clean_task:
            prefix = clean_task.split(':', 1)[0].strip()
            if prefix not in groups:
                groups[prefix] = []
                group_order.append(prefix)
            groups[prefix].append(i)
        else:
            if '__ungrouped__' not in groups:
                groups['__ungrouped__'] = []
                group_order.append('__ungrouped__')
            groups['__ungrouped__'].append(i)
    
    for group_name in group_order:
        if group_name != '__ungrouped__':
            if group_name in collapsed_groups:
                # Add collapsed group header as selectable
                items.append(('group', group_name))
            else:
                # Add all todos in expanded group
                for todo_idx in groups[group_name]:
                    items.append(('todo', todo_idx))
        else:
            # Ungrouped items always visible
            for todo_idx in groups[group_name]:
                items.append(('todo', todo_idx))
    
    return items

def main(stdscr):
    curses.curs_set(1)  # Show cursor
    stdscr.keypad(True)  # Enable special keys
    stdscr.timeout(500)  # Non-blocking getch with 500ms timeout for auto-refresh
    curses.set_escdelay(25)  # Reduce ESC key delay to 25ms
    
    # Initialize colors
    curses.start_color()
    curses.init_pair(1, 11, curses.COLOR_BLACK)  # ! prefix - bright yellow
    curses.init_pair(2, 9, curses.COLOR_BLACK)   # !! prefix - bright red
    curses.init_pair(3, 8, curses.COLOR_BLACK)   # completed - bright black (gray)
    
    todos = load_todos()
    last_mtime = get_file_mtime()
    just_saved = False  # Track if we just saved to prevent reload
    selected = 0
    if len(todos) > 0:
        selected_id = todos[0]['id']
        selected_type = 'todo'
    else:
        selected_id = None
        selected_type = 'todo'
    selected_group = None  # Track selected group name when type is 'group'
    input_text = ""
    cursor_pos = 0
    input_mode = False  # Track if user is actively typing in input field
    editing_id = None  # Track which todo is being edited (None = creating new)
    collapsed_groups = set()  # Track which groups are collapsed
    show_help = False  # Track if help screen is displayed
    hide_completed = False  # Track if completed items should be hidden
    
    while True:
        # Check if file was modified by another session
        current_mtime = get_file_mtime()
        if just_saved:
            # We just saved, update mtime but don't reload
            last_mtime = current_mtime
            just_saved = False
        elif current_mtime > last_mtime:
            # File was modified externally, reload
            todos = load_todos()
            last_mtime = current_mtime
            
            # Try to maintain selection on same item by ID
            if selected_id:
                found = False
                for i, todo in enumerate(todos):
                    if todo.get('id') == selected_id:
                        selected = i
                        found = True
                        break
                if not found:
                    # Selected item was deleted, adjust selection
                    if selected >= len(todos) and len(todos) > 0:
                        selected = len(todos) - 1
                    elif len(todos) == 0:
                        selected = 0
                        selected_id = None
            else:
                # No previous selection
                if len(todos) > 0:
                    selected = 0
                    selected_id = todos[0]['id']
        
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        
        if show_help:
            # Display help screen
            stdscr.addstr(0, 2, "TODO APP - HELP", curses.A_BOLD)
            stdscr.addstr(1, 0, "═" * width)
            
            help_text = [
                "",
                "NAVIGATION:",
                "  ↑/↓         - Navigate through todos and group headers",
                "  ←           - Collapse current group (select header)",
                "  →           - Expand selected group header",
                "  TAB         - Toggle collapse/expand all groups",
                "  Ctrl+H      - Toggle hide/show completed items",
                "",
                "TODO OPERATIONS:",
                "  Enter       - Toggle completion (when todo selected)",
                "  Enter       - Save new/edited todo (when typing)",
                "  Del/Backsp  - Delete selected todo",
                "  F2          - Edit selected todo",
                "",
                "PRIORITIES:",
                "  1           - Toggle yellow priority",
                "  2           - Toggle red priority",
                "  0           - Remove priority",
                "",
                "GROUPS:",
                "  Format: 'Group: task text' to create grouped items",
                "  Use ←/→ to collapse/expand groups",
                "",
                "OTHER:",
                "  ESC         - Exit app (or cancel input)",
                "  F1          - Toggle this help screen",
                "",
                "",
                "────────────────────────────────────────────────────────",
                "by Thomas Baekdal - baekdal.com",
                "",
                "",
                "Press any key to close help..."
            ]
            
            row = 3
            for line in help_text:
                if row < height - 1:
                    stdscr.addstr(row, 2, line[:width-4])
                    row += 1
            
            stdscr.refresh()
            stdscr.timeout(-1)  # Disable timeout, wait indefinitely
            stdscr.getch()  # Wait for any key
            stdscr.timeout(500)  # Re-enable timeout
            show_help = False
            continue
        
        # Draw header
        header = "TO-DO LIST"
        if hide_completed:
            header += " (hiding completed)"
        stdscr.addstr(0, (width - len(header)) // 2, header, curses.A_BOLD)
        stdscr.addstr(1, 0, "═" * width)
        
        # Group todos by prefix (text before colon)
        groups = {}
        group_order = []
        todo_to_group = {}  # Map todo index to group
        
        for i, todo in enumerate(todos):
            # Skip completed items if hide_completed is enabled
            if hide_completed and todo.get('done', False):
                continue
                
            task = todo['task']
            
            # Extract priority first
            priority = 0
            clean_task = task
            if task.startswith('!! '):
                priority = 2
                clean_task = task[3:]
            elif task.startswith('! '):
                priority = 1
                clean_task = task[2:]
            
            if ':' in clean_task:
                prefix = clean_task.split(':', 1)[0].strip()
                suffix = clean_task.split(':', 1)[1].strip()
                if prefix not in groups:
                    groups[prefix] = []
                    group_order.append(prefix)
                groups[prefix].append((i, suffix, todo['done'], priority))
                todo_to_group[i] = prefix
            else:
                # Ungrouped item
                if '__ungrouped__' not in groups:
                    groups['__ungrouped__'] = []
                    group_order.append('__ungrouped__')
                groups['__ungrouped__'].append((i, clean_task, todo['done'], priority))
                todo_to_group[i] = '__ungrouped__'
        
        # Draw todos with grouping
        start_row = 3
        current_row = start_row
        
        for group_name in group_order:
            group_items = groups[group_name]
            
            if group_name != '__ungrouped__':
                # Draw group header
                if group_name in collapsed_groups:
                    # Show collapsed indicator with item count
                    header = f"{group_name}: [{len(group_items)} items] ▶"
                    # Highlight if this group is selected
                    attr = curses.A_REVERSE if (selected_type == 'group' and selected_group == group_name and not input_mode) else 0
                    stdscr.addstr(current_row, 2, header, curses.A_BOLD | attr)
                else:
                    header = f"{group_name}:"
                    stdscr.addstr(current_row, 2, header, curses.A_BOLD)
                current_row += 1
                
                # Skip drawing items if group is collapsed
                if group_name in collapsed_groups:
                    continue
            
            # Draw items in group
            for idx, (todo_idx, task_text, is_done, priority) in enumerate(group_items):
                # Use priority extracted during grouping, but override with gray if completed
                if is_done:
                    color_pair = 3  # Gray for completed
                else:
                    color_pair = priority
                display_text = task_text
                
                checkbox = '☒' if is_done else '☐'
                
                # Determine tree character
                if group_name != '__ungrouped__':
                    if idx == len(group_items) - 1:
                        tree_char = "└"
                    else:
                        tree_char = "├"
                    prefix = f"  {tree_char} {checkbox} "
                else:
                    prefix = f"{checkbox} "
                
                # Calculate available width for text
                available_width = width - len(prefix) - 4
                
                # Wrap text if needed
                if len(display_text) > available_width:
                    wrapped_lines = textwrap.wrap(display_text, width=available_width)
                else:
                    wrapped_lines = [display_text]
                
                # Draw first line
                first_line = prefix + wrapped_lines[0]
                attr = curses.A_REVERSE if (selected_type == 'todo' and todo_idx == selected and len(todos) > 0 and not input_mode) else 0
                if color_pair > 0:
                    attr |= curses.color_pair(color_pair)
                stdscr.addstr(current_row, 2, first_line, attr)
                current_row += 1
                
                # Draw remaining wrapped lines (indented)
                for line in wrapped_lines[1:]:
                    if group_name != '__ungrouped__':
                        indent = "     "  # Align with text after tree char and checkbox
                    else:
                        indent = "   "
                    attr = curses.A_REVERSE if (selected_type == 'todo' and todo_idx == selected and len(todos) > 0 and not input_mode) else 0
                    if color_pair > 0:
                        attr |= curses.color_pair(color_pair)
                    stdscr.addstr(current_row, 2, indent + line, attr)
                    current_row += 1
        
        # Draw input field at bottom
        input_row = height - 5
        stdscr.addstr(input_row, 0, "─" * width)
        stdscr.addstr(input_row + 1, 0, "")  # Blank line
        
        # Truncate input display if it exceeds terminal width
        input_prefix = "Edit task: " if editing_id else "New task: "
        max_input_display = width - len(input_prefix) - 1
        display_input = input_text
        display_cursor = cursor_pos
        
        if len(input_text) > max_input_display:
            # Scroll input text to keep cursor visible
            if cursor_pos > max_input_display:
                start = cursor_pos - max_input_display
                display_input = input_text[start:start + max_input_display]
                display_cursor = max_input_display
            else:
                display_input = input_text[:max_input_display]
        
        stdscr.addstr(input_row + 2, 0, f"{input_prefix}{display_input}")
        stdscr.addstr(input_row + 3, 0, "")  # Blank line
        instructions = "F1: Help | ↑/↓: Navigate | Enter: Toggle | Ctrl+H: Hide Done | ←/→: Collapse"
        stdscr.addstr(input_row + 4, 0, instructions[:width-1])
        
        # Position cursor at current position in input (limited to terminal width)
        stdscr.move(input_row + 2, len(input_prefix) + display_cursor)
        
        stdscr.refresh()
        
        # Get key input
        key = stdscr.getch()
        
        # Handle timeout (no key pressed)
        if key == -1:
            continue
        
        # Handle input
        if key == curses.KEY_F1:
            # Toggle help screen
            show_help = True
        
        elif key == curses.KEY_UP:
            if todos:
                # Build selectable items list
                selectable = build_selectable_items(todos, collapsed_groups, hide_completed)
                if selectable:
                    # Find current position
                    current_pos = -1
                    for i, (item_type, item_value) in enumerate(selectable):
                        if item_type == selected_type:
                            if item_type == 'todo' and selected_id == todos[item_value].get('id'):
                                current_pos = i
                                break
                            elif item_type == 'group' and item_value == selected_group:
                                current_pos = i
                                break
                    
                    # Move up if possible
                    if current_pos > 0:
                        new_type, new_value = selectable[current_pos - 1]
                        selected_type = new_type
                        if new_type == 'todo':
                            selected = new_value
                            selected_id = todos[new_value]['id']
                            selected_group = None
                        else:  # group
                            selected_group = new_value
                            selected_id = None
            input_mode = False  # Exit input mode
            editing_id = None  # Clear edit mode
        
        elif key == curses.KEY_DOWN:
            if todos:
                # Build selectable items list
                selectable = build_selectable_items(todos, collapsed_groups, hide_completed)
                if selectable:
                    # Find current position
                    current_pos = -1
                    for i, (item_type, item_value) in enumerate(selectable):
                        if item_type == selected_type:
                            if item_type == 'todo' and selected_id == todos[item_value].get('id'):
                                current_pos = i
                                break
                            elif item_type == 'group' and item_value == selected_group:
                                current_pos = i
                                break
                    
                    # Move down if possible
                    if current_pos < len(selectable) - 1:
                        new_type, new_value = selectable[current_pos + 1]
                        selected_type = new_type
                        if new_type == 'todo':
                            selected = new_value
                            selected_id = todos[new_value]['id']
                            selected_group = None
                        else:  # group
                            selected_group = new_value
                            selected_id = None
            input_mode = False  # Exit input mode
            editing_id = None  # Clear edit mode
        
        elif key == curses.KEY_LEFT:
            if input_mode:
                # Move cursor left in input field
                if cursor_pos > 0:
                    cursor_pos -= 1
            else:
                # Collapse current group
                if todos and len(todos) > 0 and selected_type == 'todo' and selected_id:
                    for todo in todos:
                        if todo.get('id') == selected_id:
                            group = get_todo_group(todo)
                            if group != '__ungrouped__':
                                collapsed_groups.add(group)
                                # Switch selection to the collapsed group header
                                selected_type = 'group'
                                selected_group = group
                                selected_id = None
                            break
        
        elif key == curses.KEY_RIGHT:
            if input_mode:
                # Move cursor right in input field
                if cursor_pos < len(input_text):
                    cursor_pos += 1
            else:
                # Expand group
                if selected_type == 'group' and selected_group:
                    # Expand the selected group header
                    collapsed_groups.discard(selected_group)
                    # Switch selection to first item in that group
                    for i, todo in enumerate(todos):
                        if get_todo_group(todo) == selected_group:
                            selected_type = 'todo'
                            selected = i
                            selected_id = todos[i]['id']
                            selected_group = None
                            break
                elif todos and len(todos) > 0 and selected_id:
                    # Expand current todo's group
                    for todo in todos:
                        if todo.get('id') == selected_id:
                            group = get_todo_group(todo)
                            if group != '__ungrouped__':
                                collapsed_groups.discard(group)
                            break
        
        elif key == ord('\n'):  # Enter key
            if input_text.strip() and editing_id:
                # Save edited todo
                todos = load_todos()
                for todo in todos:
                    if todo.get('id') == editing_id:
                        original_task = todo['task']
                        # Preserve priority prefix
                        priority_prefix = ''
                        if original_task.startswith('!! '):
                            priority_prefix = '!! '
                        elif original_task.startswith('! '):
                            priority_prefix = '! '
                        
                        # Preserve group prefix (text before colon)
                        group_prefix = ''
                        clean_original = original_task
                        if priority_prefix:
                            clean_original = original_task[len(priority_prefix):]
                        if ':' in clean_original:
                            group_prefix = clean_original.split(':', 1)[0] + ': '
                        
                        # Update with preserved prefixes
                        todo['task'] = priority_prefix + group_prefix + input_text.strip()
                        break
                save_todos(todos)
                just_saved = True
                # Reload to get sorted order
                todos = load_todos()
                # Find the edited item's index after sorting
                for i, todo in enumerate(todos):
                    if todo.get('id') == editing_id:
                        selected = i
                        selected_id = editing_id
                        break
                input_text = ""
                cursor_pos = 0
                input_mode = False
                editing_id = None
            elif input_text.strip():
                # Add new todo
                new_id = str(uuid.uuid4())
                todos.append({'id': new_id, 'task': input_text.strip(), 'done': False})
                save_todos(todos)
                just_saved = True
                # Reload to get sorted order
                todos = load_todos()
                # Find the new item's index after sorting
                for i, todo in enumerate(todos):
                    if todo.get('id') == new_id:
                        selected = i
                        selected_id = new_id
                        break
                input_text = ""
                cursor_pos = 0
                input_mode = False
            elif todos and not input_mode and selected_type == 'todo' and selected_id:
                # Toggle selected todo (only when not in input mode)
                todos = load_todos()
                toggled_to_complete = False
                for todo in todos:
                    if todo.get('id') == selected_id:
                        todo['done'] = not todo['done']
                        toggled_to_complete = todo['done']
                        break
                save_todos(todos)
                just_saved = True
                # Reload to maintain consistency
                todos = load_todos()
                # Find item after reload
                for i, todo in enumerate(todos):
                    if todo.get('id') == selected_id:
                        selected = i
                        selected_type = 'todo'  # Ensure type is correct
                        break
                
                # If we toggled to complete and hide_completed is on, move to next visible item
                if toggled_to_complete and hide_completed:
                    selectable = build_selectable_items(todos, collapsed_groups, hide_completed)
                    if selectable:
                        new_type, new_value = selectable[0]
                        selected_type = new_type
                        if new_type == 'todo':
                            selected = new_value
                            selected_id = todos[new_value]['id']
                            selected_group = None
                        else:
                            selected_group = new_value
                            selected_id = None
        
        elif key == curses.KEY_DC:
            # Delete key
            if input_text:
                # Delete character at cursor position (forward delete)
                if cursor_pos < len(input_text):
                    input_text = input_text[:cursor_pos] + input_text[cursor_pos+1:]
            elif not input_mode and selected_type == 'todo' and selected_id:
                # Delete selected todo only when not in input mode
                if todos and len(todos) > 0:
                    # Reload to get latest, then delete
                    todos = load_todos()
                    # Find item by selected_id and remove it
                    todos = [t for t in todos if t.get('id') != selected_id]
                    # Save directly without merge
                    with open(TODO_FILE, 'w') as f:
                        json.dump(todos, f, indent=2)
                    just_saved = True
                    if selected >= len(todos) and selected > 0:
                        selected -= 1
                    # Update selected_id to new item at selected position
                    if len(todos) > 0:
                        selected_id = todos[selected]['id']
                    else:
                        selected_id = None
        
        elif key == curses.KEY_BACKSPACE or key == 127:
            if input_text:
                # Backspace in input field
                if cursor_pos > 0:
                    input_text = input_text[:cursor_pos-1] + input_text[cursor_pos:]
                    cursor_pos -= 1
            elif not input_mode and selected_type == 'todo' and selected_id:
                # Delete selected todo only when not in input mode
                if todos and len(todos) > 0:
                    # Reload to get latest, then delete
                    todos = load_todos()
                    # Find item by selected_id and remove it
                    todos = [t for t in todos if t.get('id') != selected_id]
                    # Save directly without merge
                    with open(TODO_FILE, 'w') as f:
                        json.dump(todos, f, indent=2)
                    just_saved = True
                    if selected >= len(todos) and selected > 0:
                        selected -= 1
                    # Update selected_id to new item at selected position
                    if len(todos) > 0:
                        selected_id = todos[selected]['id']
                    else:
                        selected_id = None
        
        elif key == ord('1') and not input_text and not input_mode and selected_type == 'todo':
            # Set/toggle priority to yellow (!)
            if todos and len(todos) > 0:
                # Reload to get latest
                todos = load_todos()
                # Find and update the item by ID
                for todo in todos:
                    if todo.get('id') == selected_id:
                        task = todo['task']
                        # Check if already yellow - if so, remove priority
                        if task.startswith('! '):
                            todo['task'] = task[2:]
                        else:
                            # Remove other priority prefix if present
                            if task.startswith('!! '):
                                task = task[3:]
                            # Add yellow priority
                            todo['task'] = f"! {task}"
                        break
                save_todos(todos)
                just_saved = True
                # Reload to maintain consistency
                todos = load_todos()
                # Find item after reload
                for i, todo in enumerate(todos):
                    if todo.get('id') == selected_id:
                        selected = i
                        break
        
        elif key == ord('2') and not input_text and not input_mode and selected_type == 'todo':
            # Set/toggle priority to red (!!)
            if todos and len(todos) > 0:
                # Reload to get latest
                todos = load_todos()
                # Find and update the item by ID
                for todo in todos:
                    if todo.get('id') == selected_id:
                        task = todo['task']
                        # Check if already red - if so, remove priority
                        if task.startswith('!! '):
                            todo['task'] = task[3:]
                        else:
                            # Remove other priority prefix if present
                            if task.startswith('! '):
                                task = task[2:]
                            # Add red priority
                            todo['task'] = f"!! {task}"
                        break
                save_todos(todos)
                just_saved = True
                # Reload to maintain consistency
                todos = load_todos()
                # Find item after reload
                for i, todo in enumerate(todos):
                    if todo.get('id') == selected_id:
                        selected = i
                        break
        
        elif key == ord('0') and not input_text and not input_mode and selected_type == 'todo':
            # Remove priority
            if todos and len(todos) > 0:
                # Reload to get latest
                todos = load_todos()
                # Find and update the item by ID
                for todo in todos:
                    if todo.get('id') == selected_id:
                        task = todo['task']
                        # Remove existing priority prefix
                        if task.startswith('!! '):
                            todo['task'] = task[3:]
                        elif task.startswith('! '):
                            todo['task'] = task[2:]
                        break
                save_todos(todos)
                just_saved = True
                # Reload to maintain consistency
                todos = load_todos()
                # Find item after reload
                for i, todo in enumerate(todos):
                    if todo.get('id') == selected_id:
                        selected = i
                        break
        
        elif key == 8 and not input_mode:  # CTRL+h - toggle hide completed
            # Toggle hide completed items
            hide_completed = not hide_completed
            # Ensure selected item is visible after toggling
            if hide_completed and selected_type == 'todo' and selected_id:
                # Check if selected item is now hidden (completed)
                for todo in todos:
                    if todo.get('id') == selected_id and todo.get('done', False):
                        # Find next visible item
                        selectable = build_selectable_items(todos, collapsed_groups, hide_completed)
                        if selectable:
                            new_type, new_value = selectable[0]
                            selected_type = new_type
                            if new_type == 'todo':
                                selected = new_value
                                selected_id = todos[new_value]['id']
                                selected_group = None
                            else:
                                selected_group = new_value
                                selected_id = None
                        break
        
        elif key == ord('\t') and not input_mode:  # TAB key
            # Toggle all groups collapsed/expanded
            # First, get all group names from current todos
            all_groups = set()
            for todo in todos:
                group = get_todo_group(todo)
                if group != '__ungrouped__':
                    all_groups.add(group)
            
            if collapsed_groups:
                # Expand all
                collapsed_groups.clear()
                # If a group header was selected, select first todo in that group
                if selected_type == 'group' and selected_group:
                    for i, todo in enumerate(todos):
                        if get_todo_group(todo) == selected_group:
                            selected_type = 'todo'
                            selected = i
                            selected_id = todos[i]['id']
                            break
            else:
                # Collapse all groups
                collapsed_groups.update(all_groups)
                # If current selection is a todo in a collapsible group, select that group header
                if selected_type == 'todo' and selected_id and todos:
                    for todo in todos:
                        if todo.get('id') == selected_id:
                            group = get_todo_group(todo)
                            if group in collapsed_groups:
                                selected_type = 'group'
                                selected_group = group
                                selected_id = None
                            break
        
        elif key == curses.KEY_F2 and not input_mode and selected_type == 'todo':
            # F2 to edit selected todo
            if todos and len(todos) > 0 and selected_id:
                # Find the selected todo by ID
                for todo in todos:
                    if todo.get('id') == selected_id:
                        task = todo['task']
                        # Remove priority prefix for editing
                        if task.startswith('!! '):
                            task = task[3:]
                        elif task.startswith('! '):
                            task = task[2:]
                        # Remove group prefix (text before colon) for editing
                        if ':' in task:
                            task = task.split(':', 1)[1].strip()
                        # Populate input field
                        input_text = task
                        cursor_pos = len(input_text)
                        editing_id = selected_id
                        input_mode = True
                        break
        
        elif key == 27:  # ESC key
            if input_mode or editing_id:
                # Cancel editing/input
                input_text = ""
                cursor_pos = 0
                input_mode = False
                editing_id = None
            else:
                # Exit app
                break
        
        elif 32 <= key <= 126:  # Printable characters
            input_text = input_text[:cursor_pos] + chr(key) + input_text[cursor_pos:]
            cursor_pos += 1
            input_mode = True  # Enter input mode when typing

if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        # Handle CTRL+C gracefully
        pass
