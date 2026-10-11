import tempfile
import os
import pytest
from core.parser import parse_file, _parse_python_regex

PYTHON_CODE = '''"""Module to validate user login details."""

import os
from database import get_connection

class UserValidator:
    """Class to perform validations."""
    pass

def validate_login(username, password):
    """Validate username and password."""
    return True

def generate_token(user_id):
    return "token"
'''

def test_python_regex_parser():
    imports, functions, classes = _parse_python_regex(PYTHON_CODE)
    
    assert "os" in imports
    assert "database" in imports
    assert "validate_login" in functions
    assert "generate_token" in functions
    assert "UserValidator" in classes

def test_parse_file_integration():
    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = os.path.join(temp_dir, "auth.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(PYTHON_CODE)

        meta = parse_file(temp_dir, "auth.py")

        assert meta.file_path == "auth.py"
        assert meta.language == "python"
        assert "validate_login" in meta.functions
        assert "UserValidator" in meta.classes
        assert "database" in meta.imports or "os" in meta.imports
        assert "validate user login details" in meta.summary.lower()


def test_js_ts_import_parsing():
    from core.parser import _parse_js_regex
    code = """
    import React, { useState } from 'react';
    import { Button } from '@/components/ui/button';
    import type { UserProps } from '@/types/user';
    import './globals.css';
    export * from './constants';
    export { Header } from './Header';
    const dynamicIcon = import('./icon');
    const legacy = require('./legacy.js');

    export function Navbar({ user }: UserProps) {
        return <div>Navbar</div>;
    }

    export const Footer = () => <footer>Footer</footer>;
    class ModalContainer {}
    """
    imports, functions, classes = _parse_js_regex(code)

    assert "react" in imports
    assert "@/components/ui/button" in imports
    assert "@/types/user" in imports
    assert "./globals.css" in imports
    assert "./constants" in imports
    assert "./Header" in imports
    assert "./icon" in imports
    assert "./legacy.js" in imports
    assert "Navbar" in functions
    assert "Footer" in functions
    assert "ModalContainer" in classes
