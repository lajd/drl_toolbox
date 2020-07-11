import torch
from collections import namedtuple
from typing import List, Union, Optional, Dict, Callable
import numpy as np
# from agents.base import Agent
from tools.scores import Scores


def ensure_tensors(*args):
    outp = []
    for a in args:
        if a is None:
            outp.append(a)
        elif not isinstance(a, torch.Tensor):
            if isinstance(a, np.ndarray):
                outp.append(torch.from_numpy(a))
            elif isinstance(a, bool) or isinstance(a, int):
                outp.append(torch.LongTensor([a]))
            elif isinstance(a, float):
                outp.append(torch.FloatTensor([a]))
            else:
                raise ValueError("Unexpected type {}".format(type(a)))
        else:
            outp.append(a)
    return outp


class Experience:
    def __init__(self, state: torch.Tensor, action: torch.Tensor, reward: float, done: torch.Tensor,
                 t_step: int, next_state: Optional[torch.Tensor] = None,
                 joint_state: Optional[torch.Tensor] = None, joint_action: Optional[torch.Tensor] = None,
                 joint_next_state: Optional[torch.Tensor] = None):
        state, action, done, next_state, joint_state, joint_action = ensure_tensors(
            state, action, done, next_state, joint_state, joint_action
        )
        self.state = state
        self.action = action
        self.reward = reward
        self.done = done
        self.t_step = t_step
        self.next_state = next_state

        self.joint_state = joint_state
        self.joint_action = joint_action
        self.joint_next_state = joint_next_state

    def _get_tensor_attributes(self):
        return {k: v for k, v in self.__dict__.items() if (not callable(v) and not k.startswith('_') and isinstance(v, torch.Tensor))}

    def to(self, device: str):
        for k, v in self._get_tensor_attributes().items():
            setattr(self, k, v.to(device))
        return self

    def cpu(self):
        for k, v in self._get_tensor_attributes().items():
            setattr(self, k, v.cpu())
        return self


class ExperienceBatch:
    def __init__(self, states: torch.Tensor, actions: torch.Tensor,
                 rewards: torch.Tensor, dones: torch.Tensor, next_states: torch.Tensor,
                 sample_idxs: Optional[torch.Tensor] = None, memory_streams: Optional[List[str]] = None,
                 is_weights: Optional[torch.FloatTensor] = None, joint_states: Optional[torch.FloatTensor] = None,
                 joint_actions: Optional[torch.Tensor] = None, joint_next_states: Optional[torch.Tensor] = None):

        states, actions, rewards, dones, next_states, sample_idxs, is_weights, joint_states, joint_actions = ensure_tensors(
            states, actions, rewards, dones, next_states, sample_idxs, is_weights, joint_states, joint_actions
        )
        self.states = states
        self.actions = actions
        self.rewards = rewards
        self.dones = dones
        self.next_states = next_states
        self.sample_idxs = sample_idxs
        self.memory_streams = memory_streams
        self.is_weights = is_weights
        self.joint_states = joint_states
        self.joint_actions = joint_actions
        self.joint_next_states = joint_next_states

    def _get_tensor_attributes(self):
        return {k: v for k, v in self.__dict__.items() if (not callable(v) and not k.startswith('_') and isinstance(v, torch.Tensor))}

    def to(self, device: torch.device):
        for k, v in self._get_tensor_attributes().items():
            setattr(self, k, v.to(device))
        return self

    def shuffle(self):
        # Add random permute
        r = torch.randperm(self.states.shape[0])
        self.memory_streams = [self.memory_streams[i] for i in r.tolist()]

        for k, v in self._get_tensor_attributes():
            setattr(self, k, v[r])

    def get_norm_is_weights(self):
        if self.is_weights is None:
            raise ValueError("IS Weights are undefined")
        return self.is_weights / self.is_weights.max()

    def __len__(self):
        return len(self.states)


class Action:
    def __init__(self, value: Union[int, float, list, np.ndarray], distribution: Optional[np.array] = None):
        self.value = value
        self.distribution = distribution


class Trajectories:
    def __init__(self, policy_outputs: Union[list, np.ndarray], states: Union[list, np.ndarray], actions: Union[list, np.ndarray], rewards: Union[list, np.ndarray]):
        self.policy_outputs = policy_outputs
        self.states = states
        self.actions = actions
        self.rewards = rewards


Environment = namedtuple("Environment", field_names=["next_state", "reward", "done"])


class Brain:
    def __init__(self, brain_name: str, action_size: int, state_shape: int, observation_type: str, num_agents: int, agent,
                 preprocess_state_fn: Callable = lambda x: x, preprocess_actions_fn: Callable = lambda x: x):
        self.brain_name = brain_name
        self.action_size = action_size
        self.state_shape = state_shape
        self.num_agents = num_agents
        self.observation_type = observation_type
        self.agent = agent
        self.agent_scores = [Scores() for _ in range(self.num_agents)]

        self.preprocess_state_fn = preprocess_state_fn
        self.preprocess_actions_fn = preprocess_actions_fn

    def get_action(self, state: np.ndarray) -> Dict[str, np.ndarray]:
        # select actions and send to environment
        action = self.agent.get_action(state)
        # actions = np.random.randint(self.action_size, size=self.num_agents)
        return {self.brain_name: action}


class BrainSet:
    def __init__(self, brains: List[Brain]):
        self.brain_map = {brain.brain_name: brain for brain in brains}

    def get_actions(self, brain_states):
        brain_actions = {}
        for brain_name, state in brain_states.items():
            brain_actions.update(self.brain_map[brain_name].get_action(state))
        return brain_actions

    def get_random_actions(self, brain_states):
        brain_actions = {}
        for brain_name, state in brain_states.items():
            brain_actions.update(self.brain_map[brain_name].get_action(state))
        return brain_actions

    def brains(self):
        for b in self.brain_map.values():
            yield b

    def names(self):
        for n in self.brain_map:
            yield n

    def __getitem__(self, brain_name: str):
        return self.brain_map[brain_name]

    def __iter__(self):
        for brain_name, brain in self.brain_map.items():
            yield brain_name, brain
