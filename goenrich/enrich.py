import networkx as nx
from scipy.stats import hypergeom
from statsmodels.stats.multitest import fdrcorrection

import goenrich.export

def analyze(G, query, **kwargs):
    """ run enrichment analysis for query

    >>> G = goenrich.obo.graph('...')
    >>> background = goenrich.read.goa('...')
    >>> goenrich.enrich.set_background(G, background, ...)
    >>> df = goenrich.enrich.analyze(G, query, ...)

    :param G: Ontology graph after backgroud set
    :param query: array like of ids
    :returns: pandas.DataFrame with results
    """
    options = {
            'node_filter' : lambda node : 'p' in node,
            'show' : 'top20'
    }
    options.update(kwargs)
    pvalues = calculate_pvalues(G, query, **options)
    multiple_testing_correction(G, pvalues, **options)
    df = goenrich.export.to_frame(G, **options)
    if 'gvfile' in options:
        show = options['show']
        if show.startswith('top'):
            top = int(show.replace('top', ''))
            sig = df.sort('q').head(top).index
        else:
            raise NotImplementedError(show)
        goenrich.export.to_graphviz(G, sig, **options)
    return df
    
def set_background(G, df, entry_id, category_id):
    """ Propagate background set through the ontolgy tree
    >>> G = goenrich.obo.graph('...')
    >>> background = goenrich.read.goa('...')
    >>> goenrich.enrich.set_background(G, background, ...)
    
    :param G: ontology graph: generated by geonrich.obo.graph
    :param df: background data set: look in goenrich.read for parsers
    :param entry_id: protein or gene identifier column
    :param category_id: GO term column
    """
    M = len(df[entry_id].unique()) # total number of objects
    for n in G: # clean background attribute for changing backgrounds
        node = G.node[n]
        node['background'] = set([])
        node['M'] = M

    grouped = df.groupby(category_id)[entry_id]
    for term,entries in grouped:
        namespace = G.node[term]['namespace']
        root = G.graph['roots'][namespace]
        for path in nx.simple_paths.all_simple_paths(G, term, root):
            for n in path:
                node = G.node[n]
                node['background'] = node['background'].union(entries)

def calculate_pvalues(G, query, min_hit_size=2, min_category_size=3, max_category_size=500, **kwargs):
    """ calculate pvalues for all categories in the graph
    
    :param G: ontology graph after background was set
    :param query: array_like of identifiers
    :param min_hit_size: minimum intersection size of query and category 
    :param min_category_size: categories smaller than this number are ignored
    :param max_category_size: categories larger than this number are ignored
    :returns: dictionary of term : pvalue
    """
    query_set = set(query)
    pvalues = {}
    N = len(query_set)
    for i in G:
        node = G.node[i]
        # reset all query related attributes
        for attr in ['query', 'n', 'N', 'hits', 'x', 'p', 'q', 'significant']:
            if attr in node:
                del node[attr]

        background = node.get('background', set([]))
        n = len(background)
        if max_category_size < n < min_category_size:
            continue
        node['n'] = n
        hits = query_set.intersection(background)
        x = len(hits)
        if x < min_hit_size:
            continue
        else:
            node['query'] = query_set
            node['N'] = N
            node['hits'] = hits
            node['x'] = x
            M, n = node['M'], node['n']
            p = hypergeom.sf(x, M, n, N)

            node['p'] = p
            pvalues[i] = p
    return pvalues


def multiple_testing_correction(G, pvalues, alpha=0.05, method='benjamini-hochberg', **kwargs):
    """ correct pvalues for multiple testing and add corrected `q` value
    :param alpha: significance level default : 0.05
    :param method: multiple testing correction method [bonferroni|benjamini-hochberg]
    """
    G.graph.update({ 'multiple-testing-correction': method,
        'alpha' : alpha })
    if method == 'bonferroni':
        n = len(pvalues.values())
        for term,p in pvalues.items():
            node = G.node[term]
            q = p * n
            node['q'] = q
            node['significant'] = q < 0.05
    elif method == 'benjamini-hochberg':
        terms, ps = zip(*pvalues.items())
        rejs, qs = fdrcorrection(ps, alpha)
        for term, q, rej in zip(terms, qs, rejs):
            node = G.node[term]
            node['q'] = q
            node['significant'] = rej
    else:
        raise ValueError(method)
