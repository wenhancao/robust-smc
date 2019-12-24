import matplotlib.pyplot as plt

from experiment_utilities import pickle_load

BETA = [0.001, 0.005, 0.01, 0.05, 0.1, 0.2, 0.5, 0.8]
CONTAMINATION = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]
LABELS = ['Kaman Filter', 'BPF'] + [f'Robustified BPF - beta = {b}' for b in BETA]
TITLES = [
    'Displacement in $x$ direction',
    'Displacement in $y$ direction',
    'Velocity in $x$ direction',
    "Velocity in $y$ direction"
]

NUM_LATENT = 4


def plot(results_file, nrows, ncols, figsize, save_path=None):
    kalman_data, vanilla_bpf_data, robust_bpf_data = pickle_load(results_file)
    fig, ax = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize, dpi=150, sharex=True)
    ax = ax.flatten()
    for var in range(NUM_LATENT):
        ax[var].set_yscale('log')
        boxes = [kalman_data[:, var], vanilla_bpf_data[:, var]] + [robust_bpf_data[:, i, var] for i in range(len(BETA))]
        ax[var].boxplot(boxes)
        ax[var].set_title(TITLES[var])
        ax[var].set_ylabel('SMSE')
        xtickNames = plt.setp(ax[var], xticklabels=LABELS)
        plt.setp(xtickNames, fontsize=12, rotation=-45)

    if save_path:
        plt.savefig(save_path)
    plt.show()


if __name__ == '__main__':
    for contamination in CONTAMINATION:
        plot(
            f'./results/constant-velocity/beta-sweep-contamination-{contamination}.pk',
            nrows=4,
            ncols=1,
            figsize=(20, 14),
            save_path=f'./figures/constant-velocity/beta-sweep-contamination-{contamination}.pdf'
        )
