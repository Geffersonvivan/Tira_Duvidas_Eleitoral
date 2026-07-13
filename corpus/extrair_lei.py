"""Extrai a redação VIGENTE de uma lei do Planalto (texto puro).

Uso: baixe o HTML com UA de navegador, converta em texto e rode:
    curl -A "Mozilla/5.0" URL > lei.html
    # (strip de tags -> lei.txt, ver README do corpus)
    python corpus/extrair_lei.py lei.txt > lei_vigente.txt

Regra: o Planalto lista a redação original e as alterações de cada artigo/§
consecutivamente; a ÚLTIMA versão é a vigente. Este script mantém só a última
de cada unidade e remove anotações "(Redação dada...)", "(Incluído...)", etc.
Sempre CONFERIR por amostragem antes de ingerir (jurídico).
"""

import re, sys

def limpar_lei(txt: str) -> str:
    # 1) flatten line-wrapping -> tudo em espaços simples
    flat = re.sub(r'[ \t]*\n[ \t]*', ' ', txt)
    flat = re.sub(r'\s{2,}', ' ', flat).strip()
    # 2) normaliza ordinais "1 o"/"1 º" -> "1º"
    flat = re.sub(r'(\d)\s*[ºoO]\b', r'\1º', flat)
    # 3) remove anotações de vigência (parênteses com marcadores legislativos)
    flat = re.sub(r'\((?:Reda[çc][aã]o dada|Inclu[ií]do|Revogad[oa]|Vide|VETADO|Vig[êe]ncia|Regulamento|Produ[çc][aã]o de efeito)[^)]*\)', '', flat, flags=re.I)
    flat = re.sub(r'\s{2,}', ' ', flat)
    # 4) split em blocos por cabeçalho de unidade
    hdr = r'(?=(?:Art\.\s*\d+(?:-[A-Z])?\.|§\s*\d+º?(?:-[A-Z])?|Par[áa]grafo [úu]nico|(?<![A-Za-zÀ-ú])[IVXLC]{1,4}\s*-|(?<![A-Za-zÀ-ú])[a-z]\)))'
    partes = [p.strip() for p in re.split(hdr, flat) if p and p.strip()]
    # 5) chave de unidade (para dedup de consecutivos)
    def chave(b):
        m = re.match(r'Art\.\s*(\d+(?:-[A-Z])?)', b);  # artigo
        if m: return ('art', m.group(1))
        m = re.match(r'§\s*(\d+(?:-[A-Z])?)', b)
        if m: return ('par', m.group(1))
        m = re.match(r'Par[áa]grafo [úu]nico', b)
        if m: return ('pu', '')
        m = re.match(r'([IVXLC]{1,4})\s*-', b)
        if m: return ('inc', m.group(1))
        m = re.match(r'([a-z])\)', b)
        if m: return ('ali', m.group(1))
        return ('?', b[:12])
    out = []
    for b in partes:
        k = chave(b)
        if out and out[-1][0] == k:   # mesma unidade consecutiva -> substitui pela última (vigente)
            out[-1] = (k, b)
        else:
            out.append((k, b))
    # 6) descarta unidades vazias (ex.: VETADO/Revogado que ficaram só com o cabeçalho)
    linhas = []
    for k, b in out:
        b = b.strip()
        # sem conteúdo além do cabeçalho?
        corpo = re.sub(r'^(Art\.\s*\d+(?:-[A-Z])?\.|§\s*\d+º?(?:-[A-Z])?|Par[áa]grafo [úu]nico\.?|[IVXLC]{1,4}\s*-|[a-z]\))\s*', '', b).strip(' .')
        if len(corpo) < 3:
            continue
        linhas.append(b)
    return '\n'.join(linhas)

if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='utf-8').read()
    print(limpar_lei(txt))
