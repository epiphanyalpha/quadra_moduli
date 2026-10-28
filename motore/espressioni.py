"""Read legacy data projections without executing generated Python code.

This is a bounded interpreter for data expressions, not a Python sandbox.
Unsupported programs are rejected and can be replaced by a declarative plan.
"""
import ast
import operator


class EspressioneNonAmmessa(ValueError):
    pass


def proietta(definizione, fascicolo):
    env = {'fascicolo': fascicolo}
    budget = [10000]

    def limite(value):
        if isinstance(value, (str, list, tuple, dict, set)) and len(value) > 10000:
            raise EspressioneNonAmmessa('Risultato troppo grande')
        return value

    def expr(n):
        budget[0] -= 1
        if budget[0] < 0:
            raise EspressioneNonAmmessa('Limite di operazioni raggiunto')
        if isinstance(n, ast.Constant):
            return limite(n.value)
        if isinstance(n, ast.Name) and n.id in env:
            return env[n.id]
        if isinstance(n, ast.Dict):
            if any(k is None for k in n.keys):
                raise EspressioneNonAmmessa('Espansione di dizionario non ammessa')
            return {expr(k): expr(v) for k, v in zip(n.keys, n.values)}
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            return {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(n)](expr(e) for e in n.elts)
        if isinstance(n, ast.Subscript):
            obj = expr(n.value)
            if type(obj) not in (dict, list, tuple, str):
                raise EspressioneNonAmmessa('Accesso consentito solo ai dati')
            return limite(obj[expr(n.slice)])
        if isinstance(n, ast.Slice):
            return slice(*(expr(v) if v else None for v in (n.lower, n.upper, n.step)))
        if isinstance(n, ast.IfExp):
            return expr(n.body if expr(n.test) else n.orelse)
        if isinstance(n, ast.BoolOp):
            result = expr(n.values[0])
            for v in n.values[1:]:
                if (isinstance(n.op, ast.Or) and result) or (isinstance(n.op, ast.And) and not result):
                    break
                result = expr(v)
            return result
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.Not, ast.USub, ast.UAdd)):
            return {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}[type(n.op)](expr(n.operand))
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = expr(n.left), expr(n.right)
            if isinstance(n.op, ast.Mult):
                for seq, count in ((a, b), (b, a)):
                    if isinstance(seq, (str, list, tuple)) and isinstance(count, int) and len(seq)*max(count, 0) > 10000:
                        raise EspressioneNonAmmessa('Risultato troppo grande')
            return limite({ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                           ast.Div: operator.truediv}[type(n.op)](a, b))
        if isinstance(n, ast.Compare):
            a = expr(n.left)
            ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Is: operator.is_,
                   ast.IsNot: operator.is_not, ast.In: lambda a,b: a in b,
                   ast.NotIn: lambda a,b: a not in b, ast.Lt: operator.lt, ast.Gt: operator.gt}
            for op, right in zip(n.ops, n.comparators):
                b = expr(right)
                if type(op) not in ops or not ops[type(op)](a, b):
                    return False
                a = b
            return True
        if isinstance(n, ast.Call) and not n.keywords:
            args = [expr(a) for a in n.args]
            if isinstance(n.func, ast.Name):
                fun = {'str': str, 'int': int, 'float': float, 'bool': bool, 'len': len,
                       'dict': dict, 'list': list, 'tuple': tuple, 'round': round,
                       'min': min, 'max': max, 'abs': abs}.get(n.func.id)
                if fun:
                    return limite(fun(*args))
            if isinstance(n.func, ast.Attribute):
                obj = expr(n.func.value)
                # Explicit unbound methods only; object introspection is absent.
                methods = {dict: {'get': dict.get}, str: {'strip': str.strip, 'split': str.split,
                    'upper': str.upper, 'lower': str.lower, 'replace': str.replace}}
                fun = methods.get(type(obj), {}).get(n.func.attr)
                if fun:
                    return limite(fun(obj, *args))
        raise EspressioneNonAmmessa('Espressione non ammessa: ' + type(n).__name__)

    def assign(target, value):
        if isinstance(target, ast.Name) and not target.id.startswith('_'):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)) and len(target.elts) == len(value):
            for part, v in zip(target.elts, value):
                assign(part, v)
        else:
            raise EspressioneNonAmmessa('Assegnazione non ammessa')

    for statement in definizione.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue  # docstring
        if isinstance(statement, ast.Assign):
            value = expr(statement.value)
            for target in statement.targets:
                assign(target, value)
        elif isinstance(statement, ast.Return):
            return expr(statement.value)
        else:
            raise EspressioneNonAmmessa('Istruzione non ammessa: ' + type(statement).__name__)
    raise EspressioneNonAmmessa('La proiezione non restituisce dati')
