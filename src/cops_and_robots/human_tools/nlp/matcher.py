#!/usr/bin/env python
from __future__ import division
"""MODULE_DESCRIPTION"""

__author__ = "Nick Sweet"
__copyright__ = "Copyright 2015, Cohrint"
__credits__ = ["Nick Sweet", "Nisar Ahmed"]
__license__ = "GPL"
__version__ = "1.0.0"
__maintainer__ = "Nick Sweet"
__email__ = "nick.sweet@colorado.edu"
__status__ = "Development"

import logging
from itertools import chain
from collections import OrderedDict

import numpy as np
import spacy.en

from cops_and_robots.human_tools.statement_template import StatementTemplate

class Matcher(object):
    """short description of Matcher

    Parameters
    ----------
    filled_templates : tuple, optional
        Tuples generated by the `TDC_collection` class. First element is a
        string for the template type, the second element is an ordered dict
        of label/token pairs.
    """

    def __init__(self, nlp=None):
        if nlp is None:
            logging.info("Loading SpaCy...")
            self.nlp = spacy.en.English(parser=False, tagger=False)
            logging.info("Done!")
        else:
            self.nlp = nlp

        self.statement_template = StatementTemplate(add_actions=True,
                                                    add_more_relations=True,
                                                    add_more_targets=True,
                                                    add_certainties=True,
                                                    )

        # from cops_and_robots.human_tools.human import generate_human_language_template
        # self.templates = generate_human_language_template()._asdict()
        # self._flatten_templates()
        # self._create_phrase_templates()

    def find_nearest_statements(self, filled_templates):
        self.filled_templates = filled_templates
        statements = []
        for ft in self.filled_templates:
            statement_type = ft[0].strip('1234567890')
            kwargs = {}
            for label, token in ft[1].iteritems():
                comparables = self.find_comparables(label)
                sorted_comparables = self.rate_comparables(token, comparables)

                label = label.split(':')[0]
                # Use most likely statement class
                kwargs[label] = sorted_comparables[0][0]
            statement = StatementTemplate.statement_classes[statement_type](**kwargs)
            statements.append(statement)
        return statements

    def find_comparables(self, label, merge_groups=True):
        """Finds a list of comparable terms to the label.

        The merge_groups parameter determines whether groups such as,
        "grounding:object" and "grounding:area" are merged together into
        a "grounding" group.
        """
        components = label.split(':')
        comparables = self.statement_template.components

        if merge_groups:
            comparables = comparables[components[0]]
            if isinstance(comparables, dict):
                comparables = [v for values in comparables.values() for v in values]
        else:
            for component in components:
                try:
                    comparables = comparables[component]
                except KeyError:
                    continue

        return comparables

    def rate_comparables(self, token, comparables):
        """Find normalized distance between token and all comparables.
        """
        n = len(comparables)
        if token == '':
            similarities = [1] * n

        else:
            similarities = []
            for comparable in comparables:
                comparable = self.nlp(unicode(comparable))
                tok = self.nlp(unicode(token.replace('_',' ')))
                s = tok.similarity(comparable)
                similarities.append(s)
        similarities = np.array(similarities, dtype=float)
        similarities /= similarities.sum()

        sorted_comparables = [(c,s) for (s,c) in
            sorted(zip(similarities, comparables), reverse=True)]

        return sorted_comparables


    # def _flatten_templates(self):
    #     flat_templates = {}
    #     for key, value in self.templates.iteritems():
    #         if isinstance(value, dict):
    #             value = list(chain(*value.values()))

    #         #<>TODO: match keys to *unified* variable names
    #         if key == 'target_names':
    #             key = 'target'
    #         if key == 'positivities':
    #             key = 'positivity'
    #         if key == 'certainties':
    #             key = 'certainty'
    #         if key == 'relations':
    #             key = 'spatialrelation'
    #         if key == 'actions':
    #             key = 'action'
    #         if key == 'modifiers':
    #             key = 'modifier'
    #         if key == 'groundings':
    #             key = 'grounding'

    #         flat_templates[key.upper()] = value
    #     self.templates = flat_templates

    # def _create_phrase_templates(self):
    #     self.phrase_templates = {}
    #     d = OrderedDict([('I', 'I'),
    #                      ('CERTAINTY', 'know'),
    #                      ('TARGET', ''),
    #                      ('POSITIVITY', ''),
    #                      ('SPATIALRELATION', ''),
    #                      ('GROUNDING', ''),
    #                      ('.', '.'),
    #                      ])
    #     self.phrase_templates['spatial relation'] = d
    #     d = OrderedDict([('I', 'I'),
    #                      ('CERTAINTY', 'know'),
    #                      ('TARGET', ''),
    #                      ('POSITIVITY', ''),
    #                      ('ACTION', ''),
    #                      ('MODIFIER', ''),
    #                      ('GROUNDING', ''),
    #                      ('.', '.'),
    #                      ])
    #     self.phrase_templates['action'] = d

    # def find_closest_phrases(self, TDC_collection):
    #     closest = []
    #     for i, TDC in enumerate(TDC_collection.TDCs):
    #         tagged_phrase = TDC.to_tagged_phrase()
    #         p, t = self.find_closest_phrase(tagged_phrase, TDC.type)
    #         closest.append((p,t))

    #         # if 1 < i < len(self.TDC_collection.TDCs):
    #         #     print("\n and \n")
    #     return closest

    # def find_closest_phrase(self, tagged_phrase, template_type):
    #     """Find closest matching template phrases to input phrase.
    #     """
    #     # For each tagged word (word span) in the tagged phrase
    #     #<>TODO: break the independence assumption! We're assuming SRs and
    #     # Groundings are independent of one-another, for instance. Not true!            
    #     template = self.phrase_templates[template_type].copy()
    #     for tagged_word_span in tagged_phrase:
    #         tag = tagged_word_span[1]
    #         word_span = tagged_word_span[0]
    #         if tag == 'NULL':
    #             continue

    #         closest_word = self.find_closest_word(tag, word_span)
    #         template[tag] = closest_word

    #     # Delete empty values
    #     for key, value in template.iteritems():
    #         if value == '':
    #             del template[key]

    #     phrase = template_to_string(template)

    #     return phrase, template

    # def find_closest_word(self, tag, word_span):
    #     """Find the closest template word to an individual word-span, given a tag.
    #     """
    #     similarities = []

    #     for template_word in self.templates[tag]:
    #         tw = self.nlp(unicode(template_word))
    #         ws = self.nlp(unicode(word_span.replace('_',' ')))
    #         s = tw.similarity(ws)
    #         similarities.append(s)

    #     ranked_template_words = [x for (y,x) in 
    #         sorted(zip(similarities, self.templates[tag]), reverse=True)]

    #     logging.debug("\nSimilarity to '{}'".format(word_span))
    #     for word, similarity in zip(self.templates[tag], similarities):
    #         logging.debug("\t\t'{}': {}".format(word, similarity))
    #     return ranked_template_words[0]

def template_to_string(template):
    print template
    str_ = " ".join(filter(None, template.values()[:-1]))
    str_ += template.values()[-1]
    return str_

def test_matcher():
    from cops_and_robots.human_tools.nlp.templater import test_TDC_collection

    filled_templates = test_TDC_collection()
    
    matcher = Matcher()
    matcher.find_nearest_statements(filled_templates)

    # for _, statement in statements.iteritems():
    #     for s in statement:
    #         print s

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    test_matcher()

    # phrase,_ = sc.find_closest_phrase(tagged_phrase, template_type)
    # print phrase