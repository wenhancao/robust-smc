import numpy as np
import casadi as ca
from filterpy.kalman import UnscentedKalmanFilter, MerweScaledSigmaPoints
from robust_smc.data import peaks


def dem(x, y, num_frequencies=4):
    """
    Synthetic Digital Elevation Model (DEM) map
    :param x: x coordinates Nx1 numpy array
    :param y: y coordinates Nx1 numpy array
    :return: z coordinates Nx1 numpy array
    """
    a = np.array([300, 80, 60, 40, 20, 10])[:num_frequencies]  # 1x6
    omega = np.array([5, 10, 20, 30, 80, 150])[:num_frequencies]  # 1x6
    omega_bar = np.array([4, 10, 20, 40, 90, 150])[:num_frequencies]  # 1x6
    q = 3 / (2.96 * 1e4)
    # q = 0.5
    peak = peaks(q * x, q * y)
    if type(x) is np.float64:
        peak += np.sum(a * np.sin(omega * q * x) * np.cos(omega_bar * q * y))
    else:
        for i in range(num_frequencies):
            peak += a[i] * np.sin(omega[i] * q * x) * np.cos(omega_bar[i] * q * y)

    return peak


class NonlinearMhe:
    def __init__(self, data, transition_matrix, transition_cov, observation_cov, m_0, P_0):

        self.data = data
        self.transition_matrix = transition_matrix
        self.transition_cov = transition_cov

        self.y_dim = data.shape[1]
        self.observation_cov = observation_cov * np.eye(self.y_dim)
        self.m_0 = m_0
        self.P_0 = P_0
        self.slide_window = 5
        self.x_dim = transition_cov.shape[0]
        self.time_step = 0.1

    def one_step_prediction(self, filter_mean, filter_cov):
        """
        One step kalman filter prediction
        :param filter_mean: filter distribution mean for previous time-step
        :param filter_cov:  filter distribution covariance for previous time-step
        :return:
        """
        m_bar = self.transition_matrix @ filter_mean  # Dx1
        P_bar = self.transition_matrix @ filter_cov @ self.transition_matrix.T + self.transition_cov  # DxD
        return m_bar, P_bar

    def fx(self, x, dt):
        return self.transition_matrix @ x

    def hx(self, X):
        X0 = np.array([-7.5 * 1e3, 5.0 * 1e3, 1.1 * 1e3, 88.15, -60.53, 0.0])
        num_frequencies = 6
        height = X[2] - dem(X[0], X[1], num_frequencies)
        if type(X) is np.ndarray:
            distance = np.sqrt(np.sum((X[:2] - X0[:2]) ** 2))
            return np.array([height, distance])
        else:
            distance = ca.sqrt((X[0] - X0[0]) ** 2 + (X[1] - X0[1]) ** 2)
            return ca.vertcat(height, distance)

    def f_1x(self, x, dt=0):
        k1 = 0.16
        k2 = 0.0064
        x0 = x[0] - self.time_step * 2 * k1 * x[0] ** 2 + self.time_step * 2 * k2 * x[1]
        x1 = x[1] + self.time_step * k1 * x[0] ** 2 - self.time_step * k2 * x[1]
        if type(x) is np.ndarray:
            return np.array([x0, x1])
        else:
            return ca.vertcat(x0, x1)

    def h_1x(self, x):
        return x[0] + x[1]

    def filter(self):
        """
        Run the Kalman filter
        """
        self.filter_means = [self.m_0]
        self.filter_covs = [self.P_0]
        y_seq = np.zeros((self.slide_window, self.y_dim))
        sigmas = MerweScaledSigmaPoints(n=self.x_dim, alpha=.1, beta=2., kappa=1.)
        ukf = UnscentedKalmanFilter(dim_x=self.x_dim, dim_z=self.y_dim, dt=0, hx=self.h_1x,
                                    fx=self.f_1x,
                                    points=sigmas)
        ukf.x = self.m_0
        ukf.P = self.P_0

        for t in range(self.data.shape[0]):
            ukf.predict()
            y = self.data[t]
            if not np.isnan(y).any():
                ukf.update(y)

            self.filter_covs.append(ukf.P)
            m_bar = ukf.x

            if t < self.slide_window:
                y_seq[t] = y
                self.filter_means.append(m_bar[:, None])

            else:
                y_seq[0:self.slide_window - 1] = y_seq[1:self.slide_window]
                y_seq[self.slide_window - 1] = y
                # if self.filter_covs[t - self.slide_window + 1] ==
                sol = self.casadi_mhe(self.filter_means[t - self.slide_window + 1],
                                      self.filter_covs[t - self.slide_window + 1],
                                      y_seq,
                                      slide_window=self.slide_window)
                sol = np.array(sol.full())
                m_bar = self.solve_mhe(sol)[:, None]
                self.filter_means.append(m_bar)

        self.filter_means = self.filter_means[1:]
        self.filter_covs = self.filter_covs[1:]

    def casadi_mhe(self, x_bar0, P_0, y_seq, slide_window):
        ca_x = ca.SX.sym('ca_x', self.x_dim, 1)
        ca_xi = ca.SX.sym('ca_xi', self.x_dim, 1)

        # 自变量
        ca_x_hat0 = ca.SX.sym('ca_x_hat0', self.x_dim, 1)
        ca_Xi = ca.SX.sym('ca_Xi', self.x_dim, slide_window)

        # 动态参数
        ca_x_bar0 = ca.SX.sym('ca_x_bar0', self.x_dim, 1)
        ca_P0_inv = ca.SX.sym('ca_P0_inv', self.x_dim, self.x_dim)
        ca_Y = ca.SX.sym('Y', self.y_dim, slide_window)

        # 静态参数
        ca_Q_inv = ca.DM(np.linalg.inv(self.transition_cov))
        ca_R_inv = ca.DM(np.linalg.inv(self.observation_cov))

        # 模型
        # ca_RHS = self.transition_matrix @ ca_x + ca_xi # TDDO
        ca_RHS = self.f_1x(ca_x) + ca_xi
        ca_f = ca.Function('f', [ca_x, ca_xi], [ca_RHS])

        ca_RHS = self.h_1x(ca_x)
        ca_h = ca.Function('h', [ca_x], [ca_RHS])

        ca_x_hat = ca_x_hat0
        ca_cost_fn = (ca_x_hat - ca_x_bar0).T @ ca_P0_inv @ (ca_x_hat - ca_x_bar0)  # cost function

        for k in range(slide_window):
            ca_xi = ca_Xi[:, k]
            ca_y = ca_Y[:, k]
            ca_x_hat = ca_f(ca_x_hat, ca_xi)
            ca_cost_fn = ca_cost_fn \
                         + (ca_y - ca_h(ca_x_hat)).T @ ca_R_inv @ (ca_y - ca_h(ca_x_hat)) \
                         + ca_xi.T @ ca_Q_inv @ ca_xi

        # 自变量设置
        ca_OPT_variables = ca.vertcat(
            ca_x_hat0.reshape((-1, 1)),  # Example: 3x11 ---> 33x1 where 3=states, 11=N+1
            ca_Xi.reshape((-1, 1))
        )

        # 动态参数设置
        ca_P = ca.vertcat(
            ca_x_bar0.reshape((-1, 1)),  # (2,1)
            ca_P0_inv.reshape((-1, 1)),  # (2,2)->(2,2)
            ca_Y.reshape((-1, 1))
        )

        # 求解问题设置
        ca_nlp_prob = {
            'f': ca_cost_fn,
            'x': ca_OPT_variables,
            'p': ca_P
        }

        # 优化器设置
        ca_opts = {
            'ipopt': {
                'max_iter': 2000,
                'print_level': 0,
                'acceptable_tol': 1e-8,
                'acceptable_obj_change_tol': 1e-6
            },
            'print_time': 0
        }

        ca_solver = ca.nlpsol('solver', 'ipopt', ca_nlp_prob, ca_opts)

        # 自变量上下界
        ca_lbx = ca.DM.zeros((self.x_dim + self.x_dim * slide_window, 1))
        ca_ubx = ca.DM.zeros((self.x_dim + self.x_dim * slide_window, 1))
        ca_lbx[0: self.x_dim] = -ca.inf
        ca_ubx[0: self.x_dim] = ca.inf
        ca_lbx[self.x_dim:] = -ca.inf
        ca_ubx[self.x_dim:] = ca.inf

        # 迭代初值
        x_init = np.ones([self.x_dim + self.x_dim * slide_window, 1])
        p = np.vstack((x_bar0.reshape(-1, 1), np.linalg.inv(P_0).reshape(-1, 1), y_seq.transpose().reshape(-1, 1)))

        sol = ca_solver(
            x0=x_init,
            lbx=ca_lbx,
            ubx=ca_ubx,
            p=p
        )

        return sol['x']

    def solve_mhe(self, sol):
        x = sol[0:self.x_dim]
        for i in range(self.slide_window):
            x_next = sol[
                     self.x_dim + self.x_dim * i:self.x_dim + self.x_dim * i + self.x_dim] + self.f_1x(x)
            x = x_next
        return x.flatten()
