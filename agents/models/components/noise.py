import numpy as np
import random
from copy import copy
from typing import Tuple, Optional
import torch

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class Noise:
    def __init__(self):
        pass

    def reset(self, *args):
        pass

    def sample(self, *args):
        raise NotImplementedError


class OUNoise(Noise):
    """Ornstein-Uhlenbeck process."""

    def __init__(self, size: int, seed: int, mu: float = 0., theta: float = 0.15, sigma: float = 0.2, noise_clip: Tuple[int, int] = (-0.5, 0.5)):
        """Initialize parameters and noise process."""
        super().__init__()
        self.mu = mu * np.ones(size)
        self.theta = theta
        self.sigma = sigma
        self.seed = random.seed(seed)
        self.noise_clip = noise_clip
        self.state = None
        self.reset()

    def reset(self):
        """Reset the internal state (= noise) to mean (mu)."""
        self.state = copy(self.mu)

    def sample(self, *args):
        """Update internal state and return it as a noise sample."""
        x = self.state
        dx = self.theta * (self.mu - x) + self.sigma * np.array([random.random() for _ in range(len(x))])
        self.state = x + dx
        return self.state


class GaussianNoise(Noise):
    def __init__(self, scale: float = 0.2, clip: Optional[Tuple[float, float]] = (-0.5, 0.5)):
        super().__init__()
        self.scale = scale
        self.clip = clip

    def sample(self, x: torch.Tensor):
        output_as_numpy = False
        if isinstance(x, np.ndarray):
            output_as_numpy = True
            x = torch.from_numpy(x)
        noise = torch.randn_like(x) * self.scale
        if self.clip:
            noise = noise.clamp(self.clip[0], self.clip[1])
        if output_as_numpy:
            noise = noise.numpy()
        return noise


class RandomProcess(object):
    def reset_states(self):
        pass


class GaussianProcess(Noise, RandomProcess):
    def __init__(self, std_fn, clip: Optional[Tuple[float, float]] = (-0.5, 0.5), seed=None):
        super().__init__()
        if seed:
            np.random.seed(seed)
        self.std_fn = std_fn
        self.clip = clip

    def sample(self, x: torch.Tensor):
        if isinstance(x, np.ndarray):
            x = torch.from_numpy(x)
        x = torch.randn_like(x) * self.std_fn()
        if self.clip:
            x = x.clamp(self.clip[0], self.clip[1])
        x = x.cpu().numpy()
        return x