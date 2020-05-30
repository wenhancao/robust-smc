import os
import numpy as np

from robust_smc.data import ExplosiveTANSimulator
from robust_smc.sampler import LinearGaussianBPF, RobustifiedLinearGaussianBPF, \
    LinearStudentTBPF, LinearGaussianAPF, RobustifiedLinearGaussianAPF

from tqdm import trange

from sklearn.metrics import mean_squared_error, median_absolute_error
from experiment_utilities import pickle_save

# Experiment Settings
SIMULATOR_SEED = 1992
RNG_SEED = 24
NUM_RUNS = 1#00
BETA = [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 0.8]
CONTAMINATION = [0.0, 0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]

# Sampler Settings
NUM_LATENT = 6
NUM_SAMPLES = 20#00
NOISE_STD = 20.0
FINAL_TIME = 200
TIME_STEP = 0.1

# RNG
RNG = np.random.RandomState(RNG_SEED)


def experiment_step(simulator):
    Y = simulator.renoise()

    seed = RNG.randint(0, 1000000)

    transition_matrix = simulator.transition_matrix
    transition_cov = np.diag(simulator.process_std ** 2)
    observation_cov = simulator.observation_std ** 2

    prior_std = np.array([1e-1, 1e-1, 1.0, 1e-2, 1e-2, 1e-1])
    X_init = simulator.X0[None, :] + prior_std[None, :] * RNG.randn(NUM_SAMPLES, NUM_LATENT)
    X_init = X_init.squeeze()

    # BPF Sampler
    vanilla_bpf = LinearGaussianBPF(
        data=Y,
        transition_matrix=transition_matrix,
        observation_model=simulator.observation_model,
        transition_cov=transition_cov,
        observation_cov=observation_cov,
        X_init=X_init,
        num_samples=NUM_SAMPLES,
        seed=seed
    )
    vanilla_bpf.sample()

    # BPF Sampler
    vanilla_apf = LinearGaussianAPF(
        data=Y,
        transition_matrix=transition_matrix,
        observation_model=simulator.observation_model,
        transition_cov=transition_cov,
        observation_cov=observation_cov,
        X_init=X_init,
        num_samples=NUM_SAMPLES,
        seed=seed
    )
    vanilla_apf.sample()

    # BPF with t-likelihood
    student_bpf = LinearStudentTBPF(
        data=simulator.Y,
        transition_matrix=transition_matrix,
        transition_cov=transition_cov,
        X_init=X_init,
        df=1.01,
        observation_model=simulator.observation_model,
        num_samples=NUM_SAMPLES,
        observation_cov=observation_cov,
        seed=seed,
    )
    student_bpf.sample()

    # Robust Sampler
    robust_bpfs = []
    for b in BETA:
        robust_bpf = RobustifiedLinearGaussianBPF(
            data=Y,
            beta=b,
            transition_matrix=simulator.transition_matrix,
            observation_model=simulator.observation_model,
            transition_cov=transition_cov,
            observation_cov=observation_cov,
            X_init=X_init,
            num_samples=NUM_SAMPLES,
            seed=seed
        )
        robust_bpf.sample()
        robust_bpfs.append(robust_bpf)

    # Robust Sampler
    robust_apfs = []
    for b in BETA:
        robust_apf = RobustifiedLinearGaussianAPF(
            data=Y,
            beta=b,
            transition_matrix=simulator.transition_matrix,
            observation_model=simulator.observation_model,
            transition_cov=transition_cov,
            observation_cov=observation_cov,
            X_init=X_init,
            num_samples=NUM_SAMPLES,
            seed=seed
        )
        robust_apf.sample()
        robust_apfs.append(robust_apf)

    return simulator, vanilla_bpf, vanilla_apf, student_bpf, robust_bpfs, robust_apfs


def compute_mse_and_coverage(simulator, sampler):
    trajectories = np.stack(sampler.X_trajectories)
    mean = trajectories.mean(axis=1)
    std = np.std(trajectories, axis=1)
    quantiles = np.quantile(trajectories, q=[0.05, 0.95], axis=1)
    scores = {'metrics': [], 'statistics': []}
    for var in range(NUM_LATENT):
        mse = mean_squared_error(simulator.X[:, var], mean[:, var])
        upper = simulator.X[:, var] <= quantiles[1, :, var]
        lower = simulator.X[:, var] >= quantiles[0, :, var]
        coverage = np.sum(upper * lower) / simulator.X.shape[0]
        scores['metrics'].append([mse, coverage])
        scores['statistics'].append([mean, std])
    return scores


def compute_predictive_score(simulator, sampler):
    Y_pred = np.stack([sampler.observation_model(X) for X in sampler.X_samples]).mean(axis=1)

    m = np.median(simulator.Y, axis=0)
    w = m / m.sum()

    score = median_absolute_error(simulator.Y, Y_pred, multioutput=1 / w)
    return score


def run(runs, contamination):
    process_std = None

    simulator = ExplosiveTANSimulator(
        final_time=FINAL_TIME,
        time_step=TIME_STEP,
        observation_std=NOISE_STD,
        process_std=process_std,
        contamination_probability=contamination,
        seed=SIMULATOR_SEED
    )

    metrics = {
        'vanilla_bpf': [],
        'vanilla_apf': [],
        'student_bpf': [],
        'robust_bpfs': [],
        'robust_apfs': []
    }
    predictive_results = {
        'vanilla_bpf': [],
        'vanilla_apf': [],
        'student_bpf': [],
        'robust_bpfs': [],
        'robust_apfs': []
    }

    for _ in trange(runs):
        simulator, vanilla_bpf, vanilla_apf, student_bpf, robust_bpfs, robust_apfs = experiment_step(simulator)
        metrics['vanilla_bpf'].append(compute_mse_and_coverage(simulator, vanilla_bpf))
        metrics['vanilla_apf'].append(compute_mse_and_coverage(simulator, vanilla_apf))
        metrics['student_bpf'].append(compute_mse_and_coverage(simulator, student_bpf))
        metrics['robust_bpfs'].append([compute_mse_and_coverage(simulator, robust_bpf) for robust_bpf in robust_bpfs])
        metrics['robust_apfs'].append([compute_mse_and_coverage(simulator, robust_apf) for robust_apf in robust_apfs])
        
        predictive_results['vanilla_bpf'].append(compute_predictive_score(simulator, vanilla_bpf))
        predictive_results['vanilla_apf'].append(compute_predictive_score(simulator, vanilla_apf))
        predictive_results['student_bpf'].append(compute_predictive_score(simulator, student_bpf))
        predictive_results['robust_bpfs'].append(
            [compute_predictive_score(simulator, robust_bpf) for robust_bpf in robust_bpfs]
        )
        predictive_results['robust_apfs'].append(
            [compute_predictive_score(simulator, robust_apf) for robust_apf in robust_apfs]
        )

    return metrics, predictive_results


if __name__ == '__main__':
    for contamination in CONTAMINATION:
        results, predictive_results = run(NUM_RUNS, contamination)
        results_path = './results/tan/neurips_impulsive_noise_with_student_t/'
        if not os.path.exists(results_path):
            os.makedirs(results_path)
        pickle_save(os.path.join(results_path, f'beta-sweep-contamination-{contamination}.pk'), results)
        pickle_save(
            os.path.join(results_path, f'beta-predictive-sweep-contamination-{contamination}.pk'), predictive_results)
