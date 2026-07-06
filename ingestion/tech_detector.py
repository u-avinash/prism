"""
╔══════════════════════════════════════════════════════════════════════╗
║                          P  R  I  S  M                               ║
║       Autonomous AI Incident Management System                       ║
╚══════════════════════════════════════════════════════════════════════╝

  Building an Autonomous AI Incident Management System
  with LangGraph and OpenTelemetry

  Author   : Upadhyayula Avinash
  GitHub   : https://github.com/u-avinash
  LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
  Email    : uavinash.csit@gmail.com

  Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
"""
"""
Technology detection from OTLP log content.

Detects the source technology (Java, Python, Node.js, .NET, Go, Ruby, MuleSoft, PHP, Rust)
and framework (Spring Boot, Django, Express, etc.) from stack traces and log attributes.
"""
import re
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TechProfile:
    """Detected technology profile for an incident."""
    technology: str = "unknown"          # java, python, nodejs, dotnet, go, ruby, mulesoft, php, rust
    language: str = "unknown"            # java, python, javascript, csharp, go, ruby, php, rust
    framework: Optional[str] = None      # spring, django, express, aspnetcore, gin, rails, laravel, etc.
    runtime: Optional[str] = None        # jvm, cpython, v8, clr, go-runtime, mri, zend
    confidence: float = 0.0              # 0.0 - 1.0
    signals: list = field(default_factory=list)  # evidence collected


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

# MuleSoft / Anypoint (checked FIRST — it is a JVM app, order matters)
_MULESOFT_PATTERNS = [
    r'org\.mule\.',
    r'com\.mulesoft\.',
    r'org\.mule\.runtime',
    r'mule-artifact\.json',
    r'cloudhub\.application',
    r'mule\.application',
    r'\.xml:\d+\)',
    r'MuleEvent',
    r'MuleContext',
    r'FlowRunner',
]

# Java / JVM
_JAVA_PATTERNS = [
    r'\tat [\w$.]+\.[\w$]+\([\w$]+\.java:\d+\)',
    r'Exception in thread "[\w -]+"',
    r'Caused by: [\w$.]+Exception',
    r'java\.lang\.',
    r'java\.io\.',
    r'java\.util\.',
    r'javax?\.',
    r'kotlin\.',
    r'scala\.',
    r'groovy\.',
    r'NullPointerException',
    r'IllegalArgumentException',
    r'IllegalStateException',
    r'ClassNotFoundException',
    r'NoSuchMethodException',
    r'StackOverflowError',
    r'OutOfMemoryError',
]

_JAVA_FRAMEWORK_PATTERNS = {
    'spring':      [r'org\.springframework\.', r'SpringApplication', r'@SpringBootApplication'],
    'quarkus':     [r'io\.quarkus\.', r'QuarkusApplication'],
    'micronaut':   [r'io\.micronaut\.'],
    'jakarta':     [r'jakarta\.', r'javax\.ws\.rs\.'],
    'hibernate':   [r'org\.hibernate\.', r'HibernateException'],
    'mybatis':     [r'org\.apache\.ibatis\.'],
    'struts':      [r'org\.apache\.struts\.'],
    'play':        [r'play\.api\.', r'play\.mvc\.'],
    'vertx':       [r'io\.vertx\.'],
    'grpc_java':   [r'io\.grpc\.'],
}

# Python
_PYTHON_PATTERNS = [
    r'Traceback \(most recent call last\)',
    r'File "[^"]+\.py", line \d+',
    r'  File "[^"]+", line \d+, in ',
    r'[\w]+Error: ',
    r'[\w]+Exception: ',
    r'raise [\w]+',
    r'__main__',
    r'\.py", line \d+',
    r'SyntaxError',
    r'IndentationError',
    r'AttributeError',
    r'KeyError',
    r'TypeError',
    r'ValueError',
    r'ImportError',
    r'ModuleNotFoundError',
    r'RuntimeError',
    r'RecursionError',
]

_PYTHON_FRAMEWORK_PATTERNS = {
    'django':       [r'django\.', r'from django', r'django\.core\.exceptions', r'Django'],
    'fastapi':      [r'fastapi\.', r'from fastapi', r'FastAPI', r'starlette\.'],
    'flask':        [r'flask\.', r'from flask', r'Flask\(', r'werkzeug\.'],
    'celery':       [r'celery\.', r'from celery', r'CeleryWorker'],
    'airflow':      [r'airflow\.', r'from airflow', r'DAG\('],
    'sqlalchemy':   [r'sqlalchemy\.', r'SQLAlchemyError'],
    'pydantic':     [r'pydantic\.', r'ValidationError'],
    'pytest':       [r'pytest\.', r'FAILED.*\.py'],
    'tornado':      [r'tornado\.', r'tornado\.web\.'],
    'aiohttp':      [r'aiohttp\.', r'ClientError'],
}

# Node.js / JavaScript
_NODEJS_PATTERNS = [
    r'at Object\.<anonymous> \(',
    r'at [\w.<>]+\s+\([^\)]+\.js:\d+:\d+\)',
    r'at [\w.<>]+\s+\([^\)]+\.ts:\d+:\d+\)',
    r'at [\w.<>]+\s+\(node:',
    r'ReferenceError:',
    r'TypeError: Cannot read propert',
    r'TypeError: .* is not a function',
    r'UnhandledPromiseRejectionWarning',
    r'node_modules/',
    r'\.js:\d+\)',
    r'\.mjs:\d+\)',
    r'process\.nextTick',
    r'EventEmitter',
]

_NODEJS_FRAMEWORK_PATTERNS = {
    'express':  [r'express/', r'express\.Router', r'app\.use\('],
    'nestjs':   [r'@nestjs/', r'NestApplication', r'NestFactory'],
    'nextjs':   [r'next/', r'next\.config', r'getServerSideProps'],
    'fastify':  [r'fastify/', r'Fastify\('],
    'koa':      [r'koa/', r'Koa\('],
    'hapi':     [r'@hapi/hapi', r'Hapi\.server'],
    'typeorm':  [r'typeorm/', r'TypeORMError'],
    'prisma':   [r'prisma/', r'PrismaClient', r'PrismaClientKnownRequestError'],
    'graphql':  [r'graphql/', r'GraphQLError'],
    'mongoose': [r'mongoose/', r'MongooseError'],
}

# .NET / C#
_DOTNET_PATTERNS = [
    r'at [\w.<>+]+\.[\w<>]+\([^)]*\) in [^:]+\.cs:line \d+',
    r'System\.NullReferenceException',
    r'System\.ArgumentNullException',
    r'System\.InvalidOperationException',
    r'System\.Collections\.Generic\.',
    r'Microsoft\.AspNetCore\.',
    r'System\.Threading\.Tasks\.',
    r'System\.Net\.Http\.',
    r'\.cs:line \d+',
    r'System\.Exception',
    r'System\.IO\.',
    r'System\.Data\.',
    r'NullReferenceException',
    r'ObjectDisposedException',
    r'StackOverflowException',
]

_DOTNET_FRAMEWORK_PATTERNS = {
    'aspnetcore':       [r'Microsoft\.AspNetCore\.', r'IApplicationBuilder'],
    'entityframework':  [r'Microsoft\.EntityFrameworkCore\.', r'DbContext', r'DbUpdateException'],
    'azure_functions':  [r'Microsoft\.Azure\.Functions\.', r'FunctionApp'],
    'blazor':           [r'Microsoft\.AspNetCore\.Components\.', r'Blazor'],
    'maui':             [r'Microsoft\.Maui\.'],
    'orleans':          [r'Orleans\.'],
    'signalr':          [r'Microsoft\.AspNetCore\.SignalR\.'],
    'grpc_dotnet':      [r'Grpc\.AspNetCore\.', r'Grpc\.Core\.'],
}

# Go
_GO_PATTERNS = [
    r'goroutine \d+ \[',
    r'runtime/debug\.Stack',
    r'runtime\.goexit',
    r'panic: ',
    r'\.go:\d+ \+0x',
    r'created by ',
    r'invalid memory address',
    r'index out of range \[',
    r'nil pointer dereference',
    r'interface conversion',
]

_GO_FRAMEWORK_PATTERNS = {
    'gin':      [r'github\.com/gin-gonic/gin', r'gin\.Context'],
    'echo':     [r'github\.com/labstack/echo'],
    'fiber':    [r'github\.com/gofiber/fiber'],
    'grpc_go':  [r'google\.golang\.org/grpc'],
    'gorm':     [r'gorm\.io/gorm', r'gorm\.io/driver'],
    'chi':      [r'github\.com/go-chi/chi'],
}

# Ruby
_RUBY_PATTERNS = [
    r'/[^\s]+\.rb:\d+:in `',
    r'from /[^\s]+\.rb:\d+',
    r'NameError \(undefined',
    r'NoMethodError \(',
    r'ArgumentError \(',
    r'RuntimeError \(',
    r'StandardError',
    r'ActiveRecord::',
    r'ActionController::',
    r'LoadError \(',
    r'Errno::',
]

_RUBY_FRAMEWORK_PATTERNS = {
    'rails':    [r'ActiveRecord::', r'ActionController::', r'Rails\b', r'ApplicationController'],
    'sinatra':  [r'Sinatra::', r'Sinatra::Base'],
    'sidekiq':  [r'Sidekiq::', r'Sidekiq::Worker'],
    'rspec':    [r'RSpec::', r'spec/'],
    'grape':    [r'Grape::', r'Grape::API'],
}

# PHP
_PHP_PATTERNS = [
    r'Stack trace:',
    r'#\d+ /[^\s]+\.php\(\d+\)',
    r'PHP Fatal error',
    r'PHP Warning',
    r'PHP Notice',
    r'PHP Parse error',
    r'Uncaught [\w\\]+Exception',
    r'Uncaught Error:',
    r'Call to undefined',
    r'\.php on line',
    r'Catchable fatal error',
]

_PHP_FRAMEWORK_PATTERNS = {
    'laravel':      [r'Illuminate\\', r'Laravel', r'Eloquent'],
    'symfony':      [r'Symfony\\', r'Symfony\b'],
    'wordpress':    [r'wp-content/', r'WordPress'],
    'codeigniter':  [r'CodeIgniter', r'CI_Controller'],
    'yii':          [r'yii\b', r'Yii::'],
    'zend':         [r'Zend\\', r'Laminas\\'],
}

# Rust
_RUST_PATTERNS = [
    r"thread '[\w:]+' panicked at",
    r'note: run with `RUST_BACKTRACE=1`',
    r'stack backtrace:',
    r'rust_begin_unwind',
    r'core::panicking::',
    r'std::panicking::',
    r'\.rs:\d+:\d+',
]

_RUST_FRAMEWORK_PATTERNS = {
    'tokio':  [r'tokio::', r'tokio_runtime'],
    'actix':  [r'actix_web::', r'actix::'],
    'axum':   [r'axum::', r'axum::Router'],
    'rocket': [r'rocket::', r'Rocket\b'],
    'warp':   [r'warp::', r'warp::Filter'],
    'diesel': [r'diesel::', r'diesel::result::'],
    'sqlx':   [r'sqlx::', r'sqlx::Error'],
}

# ---------------------------------------------------------------------------
# Technology registry — ordered from most-specific to least-specific
# ---------------------------------------------------------------------------
_TECH_REGISTRY = [
    {
        'technology': 'mulesoft',
        'language': 'java',
        'runtime': 'jvm',
        'patterns': _MULESOFT_PATTERNS,
        'framework_patterns': {},           # no sub-frameworks within MuleSoft scope
        'min_matches': 1,                   # single Mule class reference is enough
    },
    {
        'technology': 'dotnet',
        'language': 'csharp',
        'runtime': 'clr',
        'patterns': _DOTNET_PATTERNS,
        'framework_patterns': _DOTNET_FRAMEWORK_PATTERNS,
        'min_matches': 1,
    },
    {
        'technology': 'go',
        'language': 'go',
        'runtime': 'go-runtime',
        'patterns': _GO_PATTERNS,
        'framework_patterns': _GO_FRAMEWORK_PATTERNS,
        'min_matches': 1,
    },
    {
        'technology': 'ruby',
        'language': 'ruby',
        'runtime': 'mri',
        'patterns': _RUBY_PATTERNS,
        'framework_patterns': _RUBY_FRAMEWORK_PATTERNS,
        'min_matches': 2,
    },
    {
        'technology': 'rust',
        'language': 'rust',
        'runtime': 'rust-runtime',
        'patterns': _RUST_PATTERNS,
        'framework_patterns': _RUST_FRAMEWORK_PATTERNS,
        'min_matches': 1,
    },
    {
        'technology': 'php',
        'language': 'php',
        'runtime': 'zend',
        'patterns': _PHP_PATTERNS,
        'framework_patterns': _PHP_FRAMEWORK_PATTERNS,
        'min_matches': 1,
    },
    {
        'technology': 'nodejs',
        'language': 'javascript',
        'runtime': 'v8',
        'patterns': _NODEJS_PATTERNS,
        'framework_patterns': _NODEJS_FRAMEWORK_PATTERNS,
        'min_matches': 2,
    },
    {
        'technology': 'python',
        'language': 'python',
        'runtime': 'cpython',
        'patterns': _PYTHON_PATTERNS,
        'framework_patterns': _PYTHON_FRAMEWORK_PATTERNS,
        'min_matches': 2,
    },
    {
        'technology': 'java',
        'language': 'java',
        'runtime': 'jvm',
        'patterns': _JAVA_PATTERNS,
        'framework_patterns': _JAVA_FRAMEWORK_PATTERNS,
        'min_matches': 2,
    },
]

# Language to display name mapping
_TECH_DISPLAY = {
    'mulesoft': 'MuleSoft/Anypoint',
    'java':     'Java/JVM',
    'python':   'Python',
    'nodejs':   'Node.js/JavaScript',
    'dotnet':   '.NET/C#',
    'go':       'Go',
    'ruby':     'Ruby',
    'php':      'PHP',
    'rust':     'Rust',
    'unknown':  'Unknown',
}


class TechnologyDetector:
    """
    Detects the source technology and framework from raw log / stack trace content.

    Detection order (most-specific first):
      1. MuleSoft  (JVM app — checked before generic Java)
      2. .NET / C# (unique stack format)
      3. Go         (goroutine format)
      4. Ruby       (backtrace format)
      5. Rust       (panic format)
      6. PHP        (explicit PHP prefix)
      7. Node.js    (V8 stack format)
      8. Python     (Traceback format)
      9. Java       (generic JVM)
    """

    def detect(
        self,
        stack_trace: str = "",
        error_message: str = "",
        raw_log: str = "",
        otlp_attributes: Optional[Dict[str, Any]] = None,
    ) -> TechProfile:
        """
        Detect technology from log content.

        Args:
            stack_trace:      Stack trace text
            error_message:    Error message / title
            raw_log:          Raw full log text
            otlp_attributes:  OTLP resource/log attributes dict

        Returns:
            TechProfile with detected technology, language, framework, and confidence
        """
        combined = f"{error_message}\n{stack_trace}\n{raw_log}"

        # 1. Check OTLP attributes for explicit technology hints first
        profile = self._detect_from_attributes(otlp_attributes or {})
        if profile and profile.confidence >= 0.9:
            logger.debug("[TechDetect] Detected from OTLP attributes: %s", profile.technology)
            return profile

        # 2. Pattern matching against combined text
        for tech_entry in _TECH_REGISTRY:
            tech = tech_entry['technology']
            patterns = tech_entry['patterns']
            min_matches = tech_entry['min_matches']

            matched_patterns = []
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE | re.MULTILINE):
                    matched_patterns.append(pattern)

            if len(matched_patterns) >= min_matches:
                confidence = min(len(matched_patterns) / max(len(patterns) * 0.3, 1), 1.0)
                framework = self._detect_framework(
                    combined, tech_entry.get('framework_patterns', {})
                )
                result = TechProfile(
                    technology=tech,
                    language=tech_entry['language'],
                    framework=framework,
                    runtime=tech_entry.get('runtime'),
                    confidence=round(confidence, 3),
                    signals=matched_patterns[:5],
                )
                logger.info(
                    "[TechDetect] Detected: %s (framework=%s, confidence=%.2f, signals=%d)",
                    tech, framework, confidence, len(matched_patterns)
                )
                return result

        # 3. Fallback: unknown
        logger.debug("[TechDetect] Could not detect technology from log content")
        return TechProfile(technology='unknown', language='unknown', confidence=0.0)

    def _detect_from_attributes(
        self, attrs: Dict[str, Any]
    ) -> Optional[TechProfile]:
        """
        Detect technology from explicit OTLP resource attributes.

        Checks common OpenTelemetry semantic convention keys:
          - telemetry.sdk.language
          - process.runtime.name
          - service.framework.name  (non-standard, but used by some SDKs)
        """
        lang = (
            attrs.get('telemetry.sdk.language') or
            attrs.get('process.runtime.name') or
            attrs.get('process.runtime.description', '')
        ).lower()

        framework = (
            attrs.get('service.framework.name') or
            attrs.get('framework.name') or
            ''
        ).lower()

        # Check for MuleSoft-specific attributes first
        if any(k.startswith('mule.') or k.startswith('cloudhub.') for k in attrs):
            return TechProfile(
                technology='mulesoft', language='java', runtime='jvm',
                framework=None, confidence=0.95, signals=['otlp_mule_attributes']
            )

        lang_map = {
            'java':       ('java', 'java', 'jvm'),
            'kotlin':     ('java', 'java', 'jvm'),
            'scala':      ('java', 'java', 'jvm'),
            'python':     ('python', 'python', 'cpython'),
            'nodejs':     ('nodejs', 'javascript', 'v8'),
            'javascript': ('nodejs', 'javascript', 'v8'),
            'dotnet':     ('dotnet', 'csharp', 'clr'),
            'csharp':     ('dotnet', 'csharp', 'clr'),
            'go':         ('go', 'go', 'go-runtime'),
            'ruby':       ('ruby', 'ruby', 'mri'),
            'php':        ('php', 'php', 'zend'),
            'rust':       ('rust', 'rust', 'rust-runtime'),
            'cpp':        ('cpp', 'cpp', 'native'),
        }

        for key, (technology, language, runtime) in lang_map.items():
            if key in lang:
                return TechProfile(
                    technology=technology,
                    language=language,
                    runtime=runtime,
                    framework=framework or None,
                    confidence=0.95,
                    signals=[f'otlp_lang={lang}'],
                )

        return None

    def _detect_framework(
        self, text: str, framework_patterns: Dict[str, list]
    ) -> Optional[str]:
        """Find the best-matching framework from the combined log text."""
        best_framework = None
        best_score = 0

        for fw_name, patterns in framework_patterns.items():
            score = sum(
                1 for p in patterns
                if re.search(p, text, re.IGNORECASE | re.MULTILINE)
            )
            if score > best_score:
                best_score = score
                best_framework = fw_name

        return best_framework if best_score > 0 else None

    def display_name(self, technology: str) -> str:
        """Return a human-readable display name for a technology identifier."""
        return _TECH_DISPLAY.get(technology, technology.title())


# ---------------------------------------------------------------------------
# File path resolver — technology-aware GitHub path normalization
# ---------------------------------------------------------------------------

class TechAwarePathResolver:
    """
    Resolves bare file names or partial paths to their canonical repository
    paths based on the detected technology.
    """

    # Default source roots per technology
    _SOURCE_ROOTS = {
        'java':     ['src/main/java/', 'src/test/java/'],
        'mulesoft': ['src/main/mule/', 'src/main/app/', 'src/main/resources/dataweave/', 'src/main/resources/dw/'],
        'python':   ['src/', 'app/', ''],
        'nodejs':   ['src/', 'lib/', 'app/', ''],
        'dotnet':   ['src/', ''],
        'go':       ['cmd/', 'internal/', 'pkg/', ''],
        'ruby':     ['app/', 'lib/', ''],
        'php':      ['app/', 'src/', ''],
        'rust':     ['src/', ''],
    }

    def resolve(self, file_path: str, technology: str, class_or_module: str = '') -> str:
        """
        Attempt to normalize a file path for the given technology.

        Args:
            file_path:        Raw file path extracted from stack trace
            technology:       Detected technology identifier
            class_or_module:  Optional fully-qualified class/module name

        Returns:
            Best-guess canonical path (may still need GitHub tree search to confirm)
        """
        if not file_path:
            return file_path

        # Already has a plausible path separator — return as-is
        if '/' in file_path and not file_path.startswith('/'):
            return file_path

        # Strip leading slash
        file_path = file_path.lstrip('/')
        filename = file_path.split('/')[-1]

        if technology in ('java', 'mulesoft') and class_or_module and '.' in class_or_module:
            return self._java_class_to_path(class_or_module, filename)

        if technology == 'python' and class_or_module:
            return self._python_module_to_path(class_or_module, filename)

        # Generic: prepend most likely source root
        roots = self._SOURCE_ROOTS.get(technology, [''])
        return f"{roots[0]}{filename}" if roots[0] else filename

    def _java_class_to_path(self, fqcn: str, filename: str) -> str:
        """
        Convert a fully-qualified Java class name to a source file path.
        e.g. com.example.service.OrderService  →  src/main/java/com/example/service/OrderService.java
        """
        # Strip method name if present (com.example.Foo.doBar → com.example.Foo)
        parts = fqcn.split('.')
        # Drop if last part looks like a method (starts lowercase) or is anonymous ($1)
        if parts and (parts[-1][0].islower() or '$' in parts[-1]):
            parts = parts[:-1]

        pkg_path = '/'.join(parts)

        if filename and not filename.endswith('.java'):
            return f"src/main/java/{pkg_path}.java"
        if filename:
            return f"src/main/java/{'/'.join(parts[:-1])}/{filename}"
        return f"src/main/java/{pkg_path}.java"

    def _python_module_to_path(self, module: str, filename: str) -> str:
        """
        Convert a Python dotted module path to a file path.
        e.g. app.services.orders  →  app/services/orders.py
        """
        if filename:
            return filename
        path = module.replace('.', '/') + '.py'
        return path


# Module-level convenience instances
detector = TechnologyDetector()
path_resolver = TechAwarePathResolver()


def detect_technology(
    stack_trace: str = "",
    error_message: str = "",
    raw_log: str = "",
    otlp_attributes: Optional[Dict[str, Any]] = None,
) -> TechProfile:
    """Convenience function — detect technology from log content."""
    return detector.detect(
        stack_trace=stack_trace,
        error_message=error_message,
        raw_log=raw_log,
        otlp_attributes=otlp_attributes,
    )
