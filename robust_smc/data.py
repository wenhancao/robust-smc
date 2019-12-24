import numpy as np

from numpy.linalg import cholesky


def peaks(x, y):
    """
    Re-implementation of MATLAB's peaks function
    :param x: Nx1 Numpy array
    :param y: Nx1 Numpy array
    :return: Nx1 Numpy array
    """
    first_term = 3 * ((1 - x) ** 2) * np.exp(- (x ** 2) - ((y + 1) ** 2))
    second_term = - 10 * ((x / 5) - (x ** 3) - (y ** 5)) * np.exp(-(x ** 2 + y ** 2))
    third_term = - (1 / 3) * np.exp(-(x + 1) ** 2 + y ** 2)
    return 200 * (first_term + second_term + third_term)


def dem(x, y):
    """
    Synthetic Digital Elevation Model (DEM) map
    :param x: x coordinates Nx1 numpy array
    :param y: y coordinates Nx1 numpy array
    :return: z coordinates Nx1 numpy array
    """
    a = np.array([300, 80, 60, 40, 20, 10])[None, :]  # 1x6
    omega = np.array([5, 10, 20, 30, 80, 150])[None, :]  # 1x6
    omega_bar = np.array([4, 10, 20, 40, 90, 150])[None, :]  # 1x6
    q = 3 / (2.96 * 1e4)
    peak = peaks(q * x, q * y)
    fourier = np.sum(a * np.sin(omega * q * x) * np.cos(omega_bar * q * x), axis=1)[:, None]
    return peak + fourier


class TANSimulator:
    """
    Terrain Aided Navigation (TAN) simulator. Taken from Merlinge et. al. 2019
    """
    def __init__(self, final_time, time_step=0.1, observation_std=5,
                 X0=None, transition_matrix=None, process_std=None, seed=None):
        """
        :param final_time: final time period
        :param time_step: time step
        :param observation_std: observation noise standard deviation
        :param X0: initial state
        :param transition_matrix: transition matrix
        :param process_std: process standard deviation
        :param seed: random seed
        """
        self.final_time = final_time
        self.time_step = time_step
        self.X0 = X0 or np.array([-3.0 * 1e3, -19.2 * 1e3, 1.1 * 1e3, 211.5, 215.3, 0.0])
        self.transition_matrix = transition_matrix or np.vstack(
            [np.hstack([np.eye(3), time_step * np.eye(3)]), np.hstack([0 * np.eye(3), np.eye(3)])]
        )
        self.simulation_steps = int(final_time / time_step)
        self.observation_std = observation_std
        if process_std is None:
            process_std = np.array([0.1, 0.1, 0.3, 1.45 * 1e-2, 2.28 * 1e-2, 11.5 * 1e-2])
        self.process_std = process_std
        self.seed = seed
        self.rng = np.random.RandomState(self.seed)
        self._simulate_system()

    @staticmethod
    def observation_model(X):
        """
        TANSimulator observation model

        m = z - DEM(x, y)

        :param X: Nx6 numpy array
        :return: z-coordinates
        """
        return X[:, 2][:, None] - dem(X[:, 0][:, None], X[:, 1][:, None])

    def noise_model(self, Y):
        return self.observation_std * self.rng.randn(*Y.shape)

    def _simulate_system(self):
        """
        Simulates the TAN system
        """
        X = np.zeros((self.simulation_steps + 1, 6))
        X[0, :] = self.X0
        for t in range(self.simulation_steps):
            state_evolution = np.matmul(self.transition_matrix, X[t, :][:, None])
            process_noise = self.process_std[:, None] * self.rng.randn(6, 1)
            X[t + 1, :] = (state_evolution + process_noise)[:, 0]

        Y = self.observation_model(X)
        Y += self.noise_model(Y)
        self.X, self.Y = X, Y


class LinearTANSimulator(TANSimulator):
    """
    Terrain Aided Navigation (TAN) simulator with linear observation model.
    Adapted from Merlinge et. al. 2019
    """
    @staticmethod
    def observation_model(X):
        """
        TANSimulator observation model

        m = (x, y, z)
        """
        return X[:, :3].copy()


class ExplosiveTANSimulator(TANSimulator):
    """
    Terrain Aided Navigation (TAN) simulator with explosive noise. Taken from Merlinge et. al. 2019
    """
    def noise_model(self, Y):
        u = self.rng.rand(Y.shape[0])
        noise = np.zeros_like(Y)
        norm_loc = (u > 0.05)
        t_loc = (u <= 0.05)
        noise[norm_loc] = self.rng.randn(norm_loc.sum(), Y.shape[1])
        noise[t_loc] = self.rng.standard_t(df=0.5, size=(t_loc.sum(), Y.shape[1]))
        return self.observation_std * noise


class ConstantVelocityModel:
    """
    Constant Velosity model with Gaussian Explosion
    """
    def __init__(self, final_time, time_step=0.1, observation_cov=None,
                 explosion_scale=10.0, contamination_probability=0.05, seed=None):
        self.final_time = final_time
        self.time_step = time_step
        self.simulation_steps = int(final_time / time_step)
        self.observation_cov = np.eye(2) if observation_cov is None else observation_cov
        self.explosion_scale = explosion_scale
        self.seed = seed
        self.rng = np.random.RandomState(seed)
        self.contamination_probability = contamination_probability
        self._build_system()
        self._simulate_system()

    def _build_system(self):
        self.dim_X = 4
        self.dim_Y = 2

        transition_matrix = np.eye(self.dim_X)
        transition_matrix[0, 2] = transition_matrix[1, 3] = self.time_step
        self.transition_matrix = transition_matrix
        self.observation_matrix = np.eye(2, 4)

        off_diagonal = (self.time_step ** 2 / 2) * np.eye(self.dim_Y)
        upper_diagonal = (self.time_step ** 3 / 3) * np.eye(self.dim_Y)
        lower_diagonal = self.time_step * np.eye(self.dim_Y)
        self.process_cov = np.vstack([np.hstack([upper_diagonal, off_diagonal]),
                                      np.hstack([off_diagonal, lower_diagonal])])

        self.initial_cov = np.eye(self.dim_X)
        self.initial_state = np.array([140., 140., 50., 0.])[:, None] * self.rng.randn(self.dim_X, 1)

    def _simulate_system(self):
        L = cholesky(self.process_cov)
        R = cholesky(self.observation_cov)

        X = [self.initial_state + cholesky(self.initial_cov) @ self.rng.randn(self.dim_X, 1)]
        Y = [self.observation_matrix @ X[-1] + R @ self.rng.randn(self.dim_Y, 1)]

        for _ in range(self.simulation_steps - 1):
            X_new = self.transition_matrix @ X[-1] + L @ self.rng.randn(self.dim_X, 1)
            Y_new = self.observation_matrix @ X_new + R @ self.rng.randn(self.dim_Y, 1)

            u = self.rng.rand()
            if u < self.contamination_probability:
                Y_new += self.explosion_scale * self.rng.randn(self.dim_Y, 1)

            X.append(X_new)
            Y.append(Y_new)

        self.X = np.stack(X).squeeze(axis=-1)
        self.Y = np.stack(Y).squeeze(axis=-1)

    def renoise(self):
        R = cholesky(self.observation_cov)

        Y = []
        for X in self.X:
            Y_new = self.observation_matrix @ X[:, None] + R @ self.rng.randn(self.dim_Y, 1)

            u = self.rng.rand()
            if u < self.contamination_probability:
                Y_new += self.explosion_scale * self.rng.randn(self.dim_Y, 1)

            Y.append(Y_new)

        return np.stack(Y).squeeze(axis=-1)




