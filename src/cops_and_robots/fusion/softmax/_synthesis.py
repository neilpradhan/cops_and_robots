from __future__ import division
import logging
import numpy as np
import itertools

from cvxopt import matrix, solvers
import matplotlib.pyplot as plt
from descartes.patch import PolygonPatch

def product_model(models):
    """Generate a product model from multiple softmax models.
    """
    from softmax import Softmax

    n = len(models)  # number of measurements

    # Figure out how many terms are needed in denominator
    M = 1  # total number of terms
    for sm in models:
        M *= sm.num_classes

    # Generate lists of all parameters
    #<>TODO: keep this a numpy-only operation, as per:
    # http://stackoverflow.com/questions/1208118/using-numpy-to-build-an-array-of-all-combinations-of-two-arrays
    model_weights = []
    model_biases = []
    model_labels = []
    for i, sm in enumerate(models):
        model_weights.append(sm.weights.tolist())
        model_biases.append(sm.biases.tolist())
        model_labels.append(sm.class_labels)  # <>TODO: fix for MMS

    # Get all possible combinations of parameters
    weight_combs = list(itertools.product(*model_weights))
    bias_combs = list(itertools.product(*model_biases))
    label_combs = list(itertools.product(*model_labels))


    # Evaluate all combinations of model parameters 
    product_weights = np.empty((M, models[0].weights.shape[1]))
    product_biases = np.empty(M)
    product_labels = []
    for i, _ in enumerate(bias_combs):
        product_weights[i] = np.array(weight_combs[i]).sum(axis=0)
        product_biases[i] = np.array(bias_combs[i]).sum()
        str_ = " + ".join(label_combs[i])
        product_labels.append(str_)

    sm = Softmax(weights=product_weights,
                 biases=product_biases,
                 labels=product_labels,
                 )

    return sm

def find_redundant_constraints(G_full, h_full, break_index=-1, verbose=False):
    """Determine which constraints effect the feasible region."""
    result = []
    redundant_constraints = []
    for i, _ in enumerate(G_full):
        if i > break_index and break_index > 0:
            break
        G = np.delete(G_full, i, axis=0)
        h = np.delete(h_full, i)

        # Objective function: max c.x (or min -c.x)
        c = -G_full[i]  # use the constraint as the objective basis
        beta = h_full[i]  # maximum in the constraint basis

        # <>TODO: Check to make sure c is a dense column matrix

        G = matrix(np.asarray(G, dtype=np.float))
        h = matrix(np.asarray(h, dtype=np.float))
        c = matrix(np.asarray(c, dtype=np.float))
        solvers.options['show_progress'] = False
        sol = solvers.lp(c,G,h)
        optimal_pt = sol['x']

        # If dual is infeasible, max is unbounded (i.e. infinity)
        if sol['status'] == 'dual infeasible' or optimal_pt is None:
            optimal_val = np.inf
        else:
            optimal_val = -np.asarray(sol['primal objective'])
            optimal_pt = np.asarray(optimal_pt).reshape(G_full.shape[1])
        is_redundant = optimal_val <= beta
        if is_redundant:
            redundant_constraints.append(i)
        
        if verbose:
            logging.info('Without constraint {}, we have the following:'.format(i))
            logging.info(np.asarray(sol['x']))
            logging.info('\tOptimal value (z_i) {} at point {}.'
                  .format(optimal_val, optimal_pt))
            logging.info('\tRemoved constraint maximum (b_i) of {}.'.format(beta))
            logging.info('\tRedundant? {}\n\n'.format(is_redundant))
        result.append({'optimal value': optimal_val, 
                       'optimal point': optimal_pt,
                       'is redundant': is_redundant
                       })

    return result, redundant_constraints

def remove_redundant_constraints(G, h, **kwargs):
    """Remove redundant inequalities from a set of inequalities Gx <= h.
    """
    _, redundant_constraints = find_redundant_constraints(G, h, **kwargs)
    G = np.delete(G, redundant_constraints, axis=0)
    h = np.delete(h, redundant_constraints)
    return G, h

def generate_inequalities(softmax_model, measurement):
    """Produce inequalities in the form Gx <= h
    """
    # Identify the measurement and index
    for i, label in enumerate(softmax_model.class_labels):
        if label == measurement:
            using_subclasses = False
            break
    else:
        if hasattr(softmax_model,'subclasses'):
            for i, label in enumerate(softmax_model.subclass_labels):
                if label == measurement:
                    using_subclasses = True
                    break 
        logging.error('Measurement not found!')

    # Look at log-odds boundaries
    G = np.empty_like(np.delete(softmax_model.weights, 0, axis=0))
    h = np.empty_like(np.delete(softmax_model.biases, 0))
    k = 0
    for j, weights in enumerate(softmax_model.weights):
        if j == i:
            continue
        G[k] = -(softmax_model.weights[i] - softmax_model.weights[j])
        h[k] = (softmax_model.biases[i] - softmax_model.biases[j])
        k += 1

    return G, h

def geometric_model(models, measurements, verbose=False):
    """Generate one softmax model from others using geometric constraints.
    """
    from softmax import Softmax

    # Get the full, redundant set of inequalities from all models
    G_full = []
    h_full = []
    for i, sm in enumerate(models):
        G, h = generate_inequalities(sm, measurements[i])
        G_full.append(G)
        h_full.append(h)
    G_full = np.asarray(G_full).reshape(-1, G.shape[1])
    h_full = np.asarray(h_full).reshape(-1)

    # Remove redundant constraints to get weights and biases
    G, h = remove_redundant_constraints(G_full, h_full, verbose=verbose)
    new_weights = np.vstack(([0,0], G))
    new_biases = np.hstack((0, -h))

    # Generate a label for the important class, and generic ones for the rest
    labels = [" + ".join(measurements)]
    for i in range(h.size):
        labels.append('Class ' + str(i + 1))
    sm = Softmax(new_weights, new_biases, labels=labels)
    return sm

def find_neighbours(self):
    """Method of a Softmax model to find neighbours for all its classes.
    """
    for label, class_ in self.classes.iteritems():
        class_.find_class_neighbours()
    # print "{} has neighbours: {}".format(class_.label, class_.neighbours)

def find_class_neighbours(self):
    """Method of a Softmax class to find its neighbour classes.
    """
    G, h = generate_inequalities(self.softmax_collection, self.label)
    results, _ = find_redundant_constraints(G, h)

    neighbours = []
    i = 0
    for j in range(len(results) + 1):
        if j == self.id:
            continue
        if not results[i]['is redundant']:
            label = self.softmax_collection.class_labels[j]
            neighbours.append(label)
        i += 1
    self.neighbours = neighbours

def nearest_neighbours_model(models, measurements):
    """Generate one softmax model from each measurement class' neighbours.
    """
    from softmax import Softmax

    nn_models = []
    for i, model in enumerate(models):
        nn_weights = []
        nn_biases = []
        nn_labels = []

        model.find_neighbours()
        measurement = measurements[i]
        nn_weights.append(model.classes[measurement].weights)
        nn_biases.append(model.classes[measurement].bias)
        nn_labels.append(measurement)

        neighbours = model.classes[measurement].neighbours
        for neighbour in neighbours:
            nn_weights.append(model.classes[neighbour].weights)
            nn_biases.append(model.classes[neighbour].bias)
            nn_labels.append(neighbour)
        nn_weights =  np.asarray(nn_weights)
        nn_biases =  np.asarray(nn_biases)

        sm = Softmax(weights=nn_weights,
                     biases=nn_biases,
                     labels=nn_labels
                     )
        nn_models.append(sm)

    nn_sm = product_model(nn_models)
    return nn_sm

def product_test(models, visualize=False, create_combinations=False):
    """
    """
    sm3 = product_model(models)

    # Manually create 'front + interior'
    fi_weights = np.array([sm2.weights[0],
                           sm2.weights[1],
                           sm2.weights[2],
                           -sm1.weights[1],
                           sm2.weights[4],
                           sm1.weights[4] - sm1.weights[1],
                           ])
    fi_biases = np.array([sm2.biases[0],
                          sm2.biases[1],
                          sm2.biases[2],
                          -sm1.biases[1],
                          sm2.biases[4],
                          sm1.biases[4] -sm1.biases[1],
                          ])
    sm4 = Softmax(fi_weights, fi_biases)

    # Plotting 
    if visualize:
        fig = plt.figure(figsize=(10,10))
        ax = fig.add_subplot(2,2,1)
        sm1.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 1')

        ax = fig.add_subplot(2,2,2)
        sm2.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 2')

        ax = fig.add_subplot(2,2,3)
        sm3.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Exact Intersection')

        ax = fig.add_subplot(2,2,4, projection='3d')
        sm3.plot(class_='Front + Inside', ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title("Likelihood of 'Front + Inside'")
        ax.set_zlabel('P(D=i|X)')
        ax.zaxis._axinfo['label']['space_factor'] = 2.8

        plt.show()

    return sm3

def test_find_redundant_constraints(verbose=False, show_timing=True, n_runs=1000):
    """Tested against results of LP method in section 3.2 of [1].

    [1] S. Paulraj and P. Sumathi, "A comparative study of redundant 
    constraints identification methods in linear programming problems,"
    Math. Probl. Eng., vol. 2010.
    """
    G_full = np.array([[2, 1, 1],
                       [3, 1, 1],
                       [0, 1, 1],
                       [1, 2, 1],
                       [-1, 0, 0],
                       [0, -1, 0],
                       [0, 0, -1],
                       ], dtype=np.float)
    h_full = np.array([30,
                       26,
                       13,
                       45,
                       0,
                       0,
                       0,
                       ], dtype=np.float)
    break_index = 3

    truth_data = [{'optimal value': 21.67,
                  'optimal point': np.array([4.33, 13.00, 0.00]),
                  'is redundant': True,
                  },
                  {'optimal value': 45.,
                  'optimal point': np.array([15., 0.00, 0.00]),
                  'is redundant': False,
                  },
                  {'optimal value': 26,
                  'optimal point': np.array([0.00, 19.00, 7.00]),
                  'is redundant': False,
                  },
                  {'optimal value': 30.33,
                  'optimal point': np.array([4.33, 13.00, 0.00]),
                  'is redundant': True,
                  }]

    if show_timing:
        import timeit
        def wrapper(func, *args, **kwargs):
            def wrapped():
                return func(*args, **kwargs)
            return wrapped

        wrapped = wrapper(find_redundant_constraints, G_full, h_full, break_index, False)
        total_time = timeit.timeit(wrapped, number=n_runs)

    if verbose:
        logging.info('LINEAR PROGRAMMING CONSTRAINT REDUCTION RESULTS \n')
    if show_timing:
        logging.info('Average execution time over {} runs: {}s\n'
              .format(n_runs, total_time / n_runs))
    results, _ = find_redundant_constraints(G_full, h_full, break_index, verbose)

    # Compare with truth
    diffs = []
    for i, result in enumerate(results):
        ovd = result['optimal value'] - truth_data[i]['optimal value']
        opd = result['optimal point'] - truth_data[i]['optimal point']
        isr = result['is redundant'] == truth_data[i]['is redundant']
        diffs.append({'optimal value diff': ovd,
                      'optimal point diff': opd,
                      'redundancies agree': isr})

    logging.info("TRUTH MODEL COMPARISON\n")
    for i, diff in enumerate(diffs):
        logging.info('Constraint {}'.format(i))
        for d, v in diff.iteritems():
            logging.info('{}: {}'.format(d,v))
        logging.info('\n')

def test_box_constraints(verbose=False):
    """Remove a known redundant constraint for a box polytope.

    Constraints:
        -x1 \leq 2
        x1 \leq 2
        x1 \leq 4
        -x2 \leq 1
        x2 \leq 1
    """

    # Define our full set of inequalities of the form Ax \leq b
    G_full = np.array([[-1, 0],
                       [1, 0],
                       [1, 0],
                       [0, -1],
                       [0, 1],
                       ], dtype=np.float)
    h_full = np.array([2,
                       2,
                       4,
                       1,
                       1,
                       ], dtype=np.float)

    A,b = remove_redundant_constraints(G_full, h_full, verbose=verbose)
    return A, b

def geometric_model_test(measurements, verbose=False, visualize=False):
    poly1 = _make_regular_2D_poly(4, max_r=2, theta=np.pi/4)
    poly2 = _make_regular_2D_poly(4, origin=[1,1.5], max_r=2, theta=np.pi/4)
    bounds = [-5, -5, 5, 5]
    sm1 = intrinsic_space_model(poly=poly1, bounds=bounds)
    sm2 = intrinsic_space_model(poly=poly2, bounds=bounds)

    A1, b1 = generate_inequalities(sm1, measurements[0])
    A2, b2 = generate_inequalities(sm2, measurements[1])
    G_full = np.vstack((A1, A2))
    h_full = np.hstack((b1, b2))

    A, b = remove_redundant_constraints(G_full, h_full, verbose=verbose)
    
    new_weights = np.vstack(([0,0], A))
    new_biases = np.hstack((0, -b))

    labels = [measurements[0] + ' + ' + measurements[1]]
    for i in range(b.size):
        labels.append('Class ' + str(i + 1))
    sm3 = Softmax(new_weights, new_biases, labels=labels)
    
    if visualize:
        fig, axes = plt.subplots(1,3, figsize=(18,6))
        ax = axes[0]
        sm1.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 1: {}'.format(measurements[0]))
        ax = axes[1]
        sm2.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 2: {}'.format(measurements[1]))
        ax = axes[2]
        sm3.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title("Synthesis of the two")
        plt.show()

    return sm3

def test_synthesis_techniques(visualize=True):
    from _models import _make_regular_2D_poly, intrinsic_space_model

    # Create the softmax models to be combined
    poly1 = _make_regular_2D_poly(4, max_r=2, theta=np.pi/4)
    poly2 = _make_regular_2D_poly(4, origin=[1,1.5], max_r=2, theta=np.pi/4)
    poly3 = _make_regular_2D_poly(4, max_r=3, theta=np.pi/4)
    sm1 = intrinsic_space_model(poly=poly1)
    sm2 = intrinsic_space_model(poly=poly2)
    sm3 = intrinsic_space_model(poly=poly3)
    measurements = ['Front', 'Inside', 'Inside']
    joint_measurement = " + ".join(measurements)
    models = [sm1, sm2, sm3]

    # Synthesize the softmax models
    product_sm = product_model(models)
    neighbour_sm = nearest_neighbours_model(models, measurements)
    geometric_sm = geometric_model(models, measurements)

    # Find their differences
    neighbour_diff = prob_difference(product_sm, neighbour_sm, joint_measurement)
    geometric_diff = prob_difference(product_sm, geometric_sm, joint_measurement)

    if visualize:
        fig = plt.figure(figsize=(16,10))

        # Plot critical regions
        ax = fig.add_subplot(3,3,1)
        product_sm.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Product Model ({} terms)'
            .format(product_sm.biases.size))

        ax = fig.add_subplot(3,3,2)
        neighbour_sm.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Nearest Neighbour Model ({} terms)'
            .format(neighbour_sm.biases.size))

        ax = fig.add_subplot(3,3,3)
        geometric_sm.plot(plot_poly=True, plot_probs=False, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Geometric Model ({} terms)'
            .format(geometric_sm.biases.size))

        # Plot probabilities of measurements
        ax = fig.add_subplot(3,3,4, projection='3d')
        product_sm.plot(class_=joint_measurement, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title("Product Class: '{}'".format(joint_measurement))

        ax = fig.add_subplot(3,3,5, projection='3d')
        neighbour_sm.plot(class_=joint_measurement, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title("Nearest Neighbour Class: '{}'"
                      .format(joint_measurement))

        ax = fig.add_subplot(3,3,6, projection='3d')
        geometric_sm.plot(class_=joint_measurement, ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title("Geometric Class: '{}'".format(joint_measurement))

        # Plot probability difference
        bounds = [-5, -5, 5, 5]

        ax = fig.add_subplot(3,3,8)
        c = ax.pcolormesh(product_sm.X, product_sm.Y, neighbour_diff,)
                          # vmin=0, vmax=diff_max)
        plt.colorbar(c)
        ax.set_title("Difference between Neighbour and Product")
        ax.set_xlim(bounds[0],bounds[2])
        ax.set_ylim(bounds[1],bounds[3])

        ax = fig.add_subplot(3,3,9)
        c = ax.pcolormesh(product_sm.X, product_sm.Y, geometric_diff,)
                          # vmin=0, vmax=diff_max)
        plt.colorbar(c)
        ax.set_title("Difference between Geometric and Product")
        ax.set_xlim(bounds[0],bounds[2])
        ax.set_ylim(bounds[1],bounds[3])

        # fig.subplots_adjust(right=0.8)
        # cax = fig.add_axes([0.85, 0.15, 0.025, 0.7])
        # fig.colorbar(c, cax=cax)

        plt.show()


def prob_difference(sm1, sm2, joint_measurement):
    #<>TODO: use arbitrary bounds
    bounds = [-5, -5, 5, 5]
    res = 0.1

    probs1 = sm1.probability(class_=joint_measurement)
    probs1 = probs1.reshape(101,101)
    del sm1.probs
    max_i = np.unravel_index(probs1.argmax(), probs1.shape)
    min_i = np.unravel_index(probs1.argmin(), probs1.shape)
    sm1stats = {'max prob': probs1.max(),
                'max prob coord': np.array(max_i) * res + np.array(bounds[0:2]),
                'min prob': probs1.min(),
                'min prob coord': np.array(min_i) * res + np.array(bounds[0:2]),
                'avg prob': probs1.mean(),
                }

    probs2 = sm2.probability(class_=joint_measurement)
    probs2 = probs2.reshape(101,101)
    del sm2.probs
    sm2stats = {'max prob': probs2.max(),
                'max prob coord': np.array(max_i) * res + np.array(bounds[0:2]),
                'min prob': probs2.min(),
                'min prob coord': np.array(min_i) * res + np.array(bounds[0:2]),
                'avg prob': probs2.mean(),
                }

    prob_diff = probs2 - probs1
    prob_diff = prob_diff.reshape(101,101)

    diffstats = {'max diff': prob_diff.max(),
                 'min diff': prob_diff.min(),
                 'avg diff': prob_diff.mean()
                 }
    return prob_diff

def product_vs_lp():
    measurements = ['Front', 'Inside']
    sm1 = product_test(visualize=False)
    sm2 = geometric_model_test(measurements, visualize=False)
    combined_measurements =  [measurements[0] + ' + ' + measurements[1]]* 2
    compare_probs(sm1, sm2, measurements=combined_measurements)

def compare_probs(sm1, sm2, measurements, visualize=True, verbose=True):

    bounds = [-5, -5, 5, 5]
    res = 0.1

    probs1 = sm1.probability(class_=measurements[0])
    probs1 = probs1.reshape(101,101)
    del sm1.probs
    max_i = np.unravel_index(probs1.argmax(), probs1.shape)
    min_i = np.unravel_index(probs1.argmin(), probs1.shape)
    sm1stats = {'max prob': probs1.max(),
                'max prob coord': np.array(max_i) * res + np.array(bounds[0:2]),
                'min prob': probs1.min(),
                'min prob coord': np.array(min_i) * res + np.array(bounds[0:2]),
                'avg prob': probs1.mean(),
                }

    probs2 = sm2.probability(class_=measurements[1])
    probs2 = probs2.reshape(101,101)
    del sm2.probs
    sm2stats = {'max prob': probs2.max(),
                'max prob coord': np.array(max_i) * res + np.array(bounds[0:2]),
                'min prob': probs2.min(),
                'min prob coord': np.array(min_i) * res + np.array(bounds[0:2]),
                'avg prob': probs2.mean(),
                }

    prob_diff21 = probs2 - probs1
    prob_diff21 = prob_diff21.reshape(101,101)

    diffstats = {'max diff': prob_diff21.max(),
                 'min diff': prob_diff21.min(),
                 'avg diff': prob_diff21.mean()
                 }

    if verbose:
        print 'Exact softmax stats:'
        for key, value in sm1stats.iteritems():
            print('{}: {}'.format(key, value))

        print '\nGeometric softmax stats:'
        for key, value in sm2stats.iteritems():
            print('{}: {}'.format(key, value))
        
        print '\n Difference stats:'
        for key, value in diffstats.iteritems():
            print('{}: {}'.format(key, value))

    # Iterate scaled version of LP-generated softmax
    scales = np.linspace(0.7, 0.9, 101)
    for scale in scales:
        weights = sm2.weights * scale
        biases = sm2.biases * scale
        labels = sm2.class_labels
        sm3 = Softmax(weights,biases, labels=labels)

        # probs3 = sm3.probability(class_=measurements[1])
        probs3 = probs2 * scale
        probs3 = probs3.reshape(101,101)
        # del sm3.probs

        prob_diff31 = np.abs(probs3 - probs1)
        prob_diff31 = prob_diff31.reshape(101,101)

        print('Avg: {}, max: {}, at scale of {}'
              .format(prob_diff31.mean(), prob_diff31.max(), scale))

    if visualize:
        fig = plt.figure(figsize=(12,10))
        ax = fig.add_subplot(2,2,1, projection='3d')
        sm1.plot(class_=measurements[0], ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 1: {}'.format(measurements[0]))
        
        ax = fig.add_subplot(2,2,2, projection='3d')
        sm2.plot(class_=measurements[0], ax=ax, fig=fig, show_plot=False,
                 plot_legend=False)
        ax.set_title('Model 2: {}'.format(measurements[1]))
        
        ax = fig.add_subplot(2,2,3)
        c = ax.pcolormesh(sm1.X, sm1.Y, prob_diff21)
        ax.set_title("Difference b/w 1 & 2")
        ax.set_xlim(bounds[0],bounds[2])
        ax.set_ylim(bounds[1],bounds[3])

        ax = fig.add_subplot(2,2,4)
        c = ax.pcolormesh(sm1.X, sm1.Y, prob_diff31)
        ax.set_title("Difference b/w 1 & 2 (rescaled)")
        ax.set_xlim(bounds[0],bounds[2])
        ax.set_ylim(bounds[1],bounds[3])

        fig.subplots_adjust(right=0.8)
        cax = fig.add_axes([0.85, 0.15, 0.025, 0.7])
        fig.colorbar(c, cax=cax)
        
        plt.show()

if __name__ == '__main__':
    np.set_printoptions(precision=2, suppress=True)

    test_synthesis_techniques()

    # product_vs_lp()
    # product_test(visualize=True, create_combinations=True)
    # measurements = ['Inside', 'Right']
    # geometric_model_test(measurements, verbose=False, visualize=True)
